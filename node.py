import argparse
import textwrap
import threading
from Pyro5.api import *
import time
from queue import Queue
import json
from Pyro5.nameserver import start_ns

RELEASED = 0
WANTED = 1 
HELD = 2

MAX_ACCESS_TIME = 10  # Tempo máximo de acesso ao recurso em segundos
REQUEST_TIMEOUT = 2.0  # Tempo máximo para aguardar resposta de um nó


parser = argparse.ArgumentParser(
    description="Cliente peer to peeim",
    formatter_class=argparse.RawDescriptionHelpFormatter,
    epilog=textwrap.dedent(''' Exemplo:
       node.py -n "PeerA"  #da o nome PeerA ao peer
                           ''')
)
parser.add_argument('-n','--name',help='define o nome do peer')

args = parser.parse_args()



if args.name:
    print(f"Meu nome é {args.name}")


class Node(object):
    def __init__(self, name_or_args):
        if isinstance(name_or_args, str):
            self.nome = name_or_args
        else:
            self.nome = name_or_args.name
        self.estado = RELEASED
        # Força IPv4 para evitar problemas de localhost/IPv6
        self.daemon = Daemon(host="127.0.0.1")
        self.uri = self.daemon.register(self)
        self.nodes_ativos = []
        self.fila_pedidos = Queue()
        self.timer = None
        # contador de falhas de heartbeat por nó (chaveada pela URI)
        self._hb_failures = {}
        self.ns = 0
    
    def pedir_acesso(self,tempo,uri):
        """Pede acesso à seção crítica.
        Aguarda respostas de todos os nós ativos com timeout; remove nós inativos.
        Entra em HELD somente se todos os nós ativos concederem.
        """
        self.estado = WANTED
        mensagem = (tempo, uri)

        # Snapshot para não iterar sobre lista mutável enquanto removemos nós
        ativos_snapshot = list(self.nodes_ativos)
        total_esperado = len(ativos_snapshot)
        respostas_positivas = 0

        for uri in ativos_snapshot:
            try:
                # uri é uma string, cria novo proxy nesta thread
                proxy = Proxy(uri)
                try:
                    proxy._pyroClaimOwnership()
                except Exception:
                    pass
                # Configura timeout da chamada de pedido
                timeout_original = getattr(proxy, "_pyroTimeout", None)
                proxy._pyroTimeout = REQUEST_TIMEOUT

                concedeu = bool(proxy.ceder_acesso(mensagem))
                if concedeu:
                    respostas_positivas += 1
                # Sucesso: zera contador de falhas de heartbeat
                key = str(getattr(proxy, "_pyroUri", "desconhecido"))
                self._hb_failures[key] = 0
                # Timeout/erro: considera destino inativo e remove
                key = str(getattr(proxy, "_pyroUri", "desconhecido"))
                print(f"Timeout/erro aguardando resposta de {key}: {type(ex).__name__}: {ex}. Removendo nó.")
                try:
                    proxy._pyroRelease()
                except Exception:
                    pass
                if key in self.nodes_ativos:
                    self.nodes_ativos.remove(key)
                # Como este nó não responderá, ajuste total esperado
                total_esperado -= 1
            finally:
                # Restaura timeout do proxy
                try:
                    if timeout_original is not None:
                        proxy._pyroTimeout = timeout_original
                except Exception:
                    pass

        if respostas_positivas == total_esperado:
            self.estado = HELD
            print(f"Nó {self.nome} entrou na seção crítica (todas as respostas positivas: {respostas_positivas}/{total_esperado}).")
            # Iniciar timer para liberar automaticamente após MAX_ACCESS_TIME
            self.timer = threading.Timer(MAX_ACCESS_TIME, self.liberar_acesso)
            self.timer.start()
            return True
        else:
            print(f"Nó {self.nome} NÃO entrou na seção crítica (respostas positivas: {respostas_positivas}/{total_esperado}).")
            self.estado = RELEASED
            return False
    
    @expose
    def ceder_acesso(self,mensagem):
        """Sempre responde ao pedido: True para conceder, False para negar.
        Se negar, enfileira o pedido para referência futura.
        """
        if self.estado == RELEASED:
            return True
        else:
            self.fila_pedidos.put(mensagem)
            return False
            
    def liberar_acesso(self):
        print(f"Nó {self.nome} liberando acesso automaticamente após {MAX_ACCESS_TIME} segundos.")
        self.estado = RELEASED
        # O estado agora é RELEASED, permitindo que outros nós adquiram acesso
        self.timer = None
        # Processa fila de pedidos: envia resposta deferida para todos em ordem de tempo
        pedidos = self._drenar_fila_pedidos()
        if pedidos:
            print(f"Processando {len(pedidos)} pedido(s) enfileirado(s) ao liberar acesso.")
        for tempo, uri in pedidos:
            self._notificar_resposta_deferida(tempo, uri)
        
    @expose
    @oneway
    def enviar_heartbeat(self):
        # oneway: não retorna valor; apenas registra que recebeu
        print(f"Heartbeat recebido em {self.nome}")
        return

    @expose
    @oneway
    def notificar_liberacao(self, remetente_nome: str, remetente_uri: str, tempo_pedido: float):
        """Notificação recebida de que um nó liberou e está concedendo a resposta deferida.
        Estratégia simples: se não estamos em HELD, tentamos pedir acesso novamente.
        """
        print(f"{self.nome}: notificação de liberação recebida de {remetente_nome}. Reavaliando pedido...")
        if self.estado != HELD:
            # Tenta novo pedido em background para não bloquear
            threading.Thread(
                target=self.pedir_acesso,
                args=(time.time(), self.uri),
                daemon=True
            ).start()
        return

    def _drenar_fila_pedidos(self):
        """Retorna uma lista de pedidos (tempo, uri) ordenada por tempo (mais antigo primeiro)."""
        itens = []
        try:
            while True:
                itens.append(self.fila_pedidos.get_nowait())
        except Exception:
            pass
        # Ordena por timestamp
        try:
            itens.sort(key=lambda x: x[0])
        except Exception:
            pass
        return itens

    def _notificar_resposta_deferida(self, tempo: float, uri: str):
        """Envia uma notificação de liberação ao solicitante original (uri)."""
        try:
            proxy = Proxy(uri)
            try:
                proxy._pyroClaimOwnership()
            except Exception:
                pass
            try:
                proxy._pyroBind()
            except Exception:
                pass
            timeout_original = getattr(proxy, "_pyroTimeout", None)
            proxy._pyroTimeout = REQUEST_TIMEOUT
            proxy.notificar_liberacao(self.nome, str(self.uri), tempo)
        except Exception as ex:
            key = uri
            print(f"Falha ao notificar resposta deferida para {key}: {type(ex).__name__}: {ex}")
            # Se este nó estiver na lista de ativos, remove
            try:
                for uri_ativo in list(self.nodes_ativos):
                    if uri_ativo == key:
                        self.nodes_ativos.remove(uri_ativo)
                        break
            except Exception:
                pass
        finally:
            try:
                if 'proxy' in locals() and timeout_original is not None:
                    proxy._pyroTimeout = timeout_original
            except Exception:
                pass
        
    def gerencia_heartbeat(self):
        
        time.sleep(2)
        print("Dormindo...")

        nodes_copia = list(self.nodes_ativos)
        print("Iniciando gerenciamento de heartbeats...")
        for uri in nodes_copia:
            # uri é uma string, não um proxy
            print(f"Enviando heartbeat para nó com URI: {uri}")
            try:
                # Cria novo proxy na thread atual
                p = Proxy(uri)
                try:
                    p._pyroClaimOwnership()
                except Exception:
                    # se não suportar (ou já for nosso), segue
                    pass
                p._pyroTimeout = 2.0
                p.enviar_heartbeat()
                # sucesso: zera contador de falhas
                self._hb_failures[uri] = 0
            except Exception as ex:
                self._hb_failures[uri] = self._hb_failures.get(uri, 0) + 1
                print(f"Nó não respondeu ao heartbeat ({uri}) [falhas={self._hb_failures[uri]}]: {type(ex).__name__}: {ex}")
                # remove após 3 falhas consecutivas
                if self._hb_failures[uri] >= 3 and uri in self.nodes_ativos:
                    self.nodes_ativos.remove(uri)
                    print(f"Removido nó inativo ({uri}) após falhas consecutivas.")
    
    def gerenciar_acesso(self):
        #while temporizador != tempo_limite:
        return 1
        
    def run(self):
        # Pequeno delay para garantir que tudo está inicializado
        time.sleep(1)
        
        heartbeat_thread = threading.Thread(target=self.heartbeat_loop, daemon=True)
        heartbeat_thread.start()

        novos_nos_thread = threading.Thread(target=self.cadastra_novos_nos, args=(self.ns,), daemon=True)
        novos_nos_thread.start()
        
        print(f"Nó {self.nome} iniciado com {len(self.nodes_ativos)} peers conhecidos")
        self.daemon.requestLoop()
    
    def heartbeat_loop(self):
        while True:
            try:
                self.gerencia_heartbeat()
            except Exception as e:
                print(f"Erro no heartbeat: {e}")
                time.sleep(1) 

    def cadastra_novos_nos(self, ns):
        while True:
            try:
                # Cria um novo proxy para o NameServer nesta thread para evitar ownership issues
                ns_uri = ns._pyroUri if hasattr(ns, '_pyroUri') else None
                if ns_uri:
                    local_ns = Proxy(ns_uri)
                    try:
                        local_ns._pyroClaimOwnership()
                    except Exception:
                        pass
                    lista = local_ns.list()
                else:
                    # Fallback: tentar usar o NameServer original
                    try:
                        ns._pyroClaimOwnership()
                    except Exception:
                        pass
                    lista = ns.list()
                    
                for e in lista:
                    if str(e) != "Pyro.NameServer" and e != self.nome:
                        # Verifica se já temos este nó na lista
                        uri_str = str(lista[e])
                        if uri_str not in self.nodes_ativos:
                            print(f"Descobrindo novo nó {e} com URI {lista[e]}")
                            self.nodes_ativos.append(uri_str)
                            print(f"Nó {e} adicionado à lista de ativos. Total: {len(self.nodes_ativos)}")
                
                time.sleep(3)  # Verifica novos nós a cada 3 segundos
            except Exception as ex:
                print(f"Erro na descoberta de nós: {type(ex).__name__}: {ex}")
                time.sleep(5)  # Espera mais tempo em caso de erro

    
def ensure_nameserver(host: str = "127.0.0.1", port: int | None = 9090):
    try:
        return locate_ns()
    except Exception as e:
        print(f"NameServer não encontrado em {host}:{port} ({type(e).__name__}: {e}). Tentando iniciar um local...")
        try:
            ns_uri, ns_daemon, _ = start_ns(host=host, port=port, enableBroadcast=False)
            threading.Thread(target=ns_daemon.requestLoop, daemon=True).start()
            print(f"NameServer iniciado em {host}:{port} -> {ns_uri}")
            return locate_ns(host=host, port=port)
        except Exception as e2:
            print(f"Falha ao iniciar NameServer local: {type(e2).__name__}: {e2}")
            raise


if __name__ == "__main__":
    # Inicializa NameServer (ou conecta ao existente)
    ns = ensure_nameserver(host="127.0.0.1", port=9090)
    # Cria nó com nome vindo da CLI
    n = Node(args)

    # Registra no NameServer
    ns.register(f"{n.nome}", n.uri)

    # Descobre e conecta aos demais nós já registrados
    lista = ns.list()
    for e in lista:
        if str(e) != "Pyro.NameServer" and e != n.nome:
            print(f"Cadastrando o proxy do nó {e} que tem uri {lista[e]}")
            uri_no_ativo = lista[e]
            n.nodes_ativos.append(uri_no_ativo)
            
    n.ns = ns

    # Abre GUI e injeta Node
    try:
        import tkinter as tk
        from gui import NodeGUI
        root = tk.Tk()
        # Passa o próprio Node para a GUI
        app = NodeGUI(root, node=n)
        root.mainloop()
    except Exception as ex:
        print(f"Falha ao iniciar GUI: {type(ex).__name__}: {ex}. Executando nó sem interface gráfica...")
        print(n.nome)
        n.run()