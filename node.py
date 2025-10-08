import argparse
import textwrap
import threading
from Pyro5.api import expose,Proxy,oneway, locate_ns, Daemon
import time
from queue import Queue
import json
from Pyro5.nameserver import start_ns
import tkinter as tk
from gui import NodeGUI

RELEASED = 0
WANTED = 1 
HELD = 2

MAX_ACCESS_TIME = 10
REQUEST_TIMEOUT = 2.0
RESPONSE_TIMEOUT = 2.0
MAX_ERROR = 3


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
        self.daemon = Daemon()
        self.uri = self.daemon.register(self)
        self.nodes_ativos = []
        self.fila_pedidos = Queue()
        self.timer = None
        self.num_falhas_heartbeat = {}
        self.ns = 0
        self._log_callback = None
        self.tempo_pedido = None

    def set_logger(self, callback):
        self._log_callback = callback

    def _log(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {self.nome}: {msg}"
        print(line)
        if callable(self._log_callback):
            self._log_callback(line)
 
    def _log_console(self, msg: str):
        ts = time.strftime("%H:%M:%S")
        line = f"[{ts}] {self.nome}: {msg}"
        print(line)
    
    def pedir_acesso(self,tempo,uri):
        if self.tempo_pedido is None:
            self.tempo_pedido = tempo
        self.estado = WANTED
        mensagem = (self.tempo_pedido, uri)

        ativos = list(self.nodes_ativos)
        total_esperado = 0
        respostas_positivas = 0

        for uri in ativos:
            proxy = None
            timeout_original = None
            try:
                proxy = Proxy(uri)
                proxy._pyroClaimOwnership()

                timeout_original = proxy._pyroTimeout
                proxy._pyroTimeout = REQUEST_TIMEOUT

                concedeu = bool(proxy.ceder_acesso(mensagem))
                total_esperado += 1
                if concedeu:
                    respostas_positivas += 1

                key = proxy._pyroUri
                self.num_falhas_heartbeat[key] = 0
            except Exception as ex:
                key = uri
                self._log_console(f"Timeout/erro aguardando resposta de {key}. Removendo nó. Motivo: {type(ex).__name__}: {ex}")
                if proxy is not None:
                    proxy._pyroRelease()
                if key in self.nodes_ativos:
                    self.nodes_ativos.remove(key)
                    
            finally:
                if proxy is not None and timeout_original is not None:
                    proxy._pyroTimeout = timeout_original

        if respostas_positivas == total_esperado:
            self.estado = HELD
            self._log(f"ENTROU na seção crítica (todas as respostas positivas: {respostas_positivas}/{total_esperado}). Agora COM ACESSO ao recurso.")
            self.timer = threading.Timer(MAX_ACCESS_TIME, self.liberar_acesso)
            self.timer.start()
            return True
        else:
            self._log_console(f"NÃO entrou na seção crítica (respostas positivas: {respostas_positivas}/{total_esperado}). Permanecendo em WANTED.")
            return False
    
    @expose
    def ceder_acesso(self,mensagem):
        if self.estado == RELEASED:
            req_ts, req_uri = mensagem
            self._log_console(f"Concedendo acesso para pedido de {req_uri} (ts={req_ts}).")
            return True
        elif self.estado == HELD:
            # Não pode conceder agora, enfileira
            self.fila_pedidos.put(mensagem)
            req_ts, req_uri = mensagem
            self._log_console(f"Deferindo (HELD). Pedido de {req_uri} enfileirado (ts={req_ts}).")
            return False
        else:
            req_ts, req_uri = mensagem
            
            my_ts = self.tempo_pedido if self.tempo_pedido is not None else float('inf')
            my_id = str(self.uri)
            other_id = str(req_uri)

            concede = (req_ts < my_ts) or (req_ts == my_ts and other_id < my_id)
            if concede:
                self._log_console(f"Concedendo (WANTED) para {other_id} ts={req_ts} (meu ts={my_ts}).")
                return True
            else:
                self.fila_pedidos.put(mensagem)
                self._log_console(f"Deferindo (WANTED) para {other_id} ts={req_ts} (meu ts={my_ts}). Pedido enfileirado.")
                return False
            
    def liberar_acesso(self):
        self._log(f"Liberando/Perdendo acesso ao recurso (timeout {MAX_ACCESS_TIME}s atingido).")
        self.estado = RELEASED
        self.tempo_pedido = None
        self.timer = None
        pedidos = self.ordena_fila_pedidos()
        if pedidos:
            self._log_console(f"Processando {len(pedidos)} pedido(s) enfileirado(s) ao liberar acesso.")
        for tempo, uri in pedidos:
            self._notificar_resposta_deferida(tempo, uri)
        
    @expose
    @oneway
    def enviar_heartbeat(self):
        self._log_console("Heartbeat recebido.")
        return

    @expose
    @oneway
    def notificar_liberacao(self, remetente_nome: str, remetente_uri: str, tempo_pedido: float):
        self._log_console(f"Notificação de liberação recebida de {remetente_nome}. Reavaliando pedido...")
        if self.estado != HELD:
            # Tenta novo pedido em background para não bloquear
            threading.Thread(
                target=self.pedir_acesso,
                args=(self.tempo_pedido if self.tempo_pedido is not None else time.time(), self.uri),
                daemon=True
            ).start()
        return

    def ordena_fila_pedidos(self):
        itens = []
        for e in range(0,self.fila_pedidos.qsize()):
            itens.append(self.fila_pedidos.get_nowait())
        itens.sort(key=lambda x: x[0]) #ordena pelo tempo [(tempo, uri)]
        return itens

    def _notificar_resposta_deferida(self, tempo: float, uri: str):
        try:
            proxy = Proxy(uri)
            proxy._pyroClaimOwnership()
            proxy._pyroBind()
          
            timeout_original = proxy._pyroTimeout
            proxy._pyroTimeout = REQUEST_TIMEOUT
            proxy.notificar_liberacao(self.nome, str(self.uri), tempo)
        except Exception as ex:
            key = uri
            self._log_console(f"Falha ao notificar resposta deferida para {key}: {type(ex).__name__}: {ex}")
            for uri_ativo in list(self.nodes_ativos):
                if uri_ativo == key:
                    self.nodes_ativos.remove(uri_ativo)
                    break
            
        
    def gerencia_heartbeat(self):
        time.sleep(2)
        self._log_console("Dormindo...")

        nodes_copia = list(self.nodes_ativos)
        for uri in nodes_copia:
            self._log_console(f"Enviando heartbeat para nó com URI: {uri}")
            try:
                p = Proxy(uri)
                p._pyroClaimOwnership()

                p._pyroTimeout = RESPONSE_TIMEOUT
                p.enviar_heartbeat()
                self.num_falhas_heartbeat[uri] = 0
            except Exception as ex:
                self.num_falhas_heartbeat[uri] = self.num_falhas_heartbeat.get(uri, 0) + 1
                self._log_console(f"Nó não respondeu ao heartbeat ({uri}) [falhas={self.num_falhas_heartbeat[uri]}]: {type(ex).__name__}: {ex}")
                # remove após 3 falhas consecutivas
                if self.num_falhas_heartbeat[uri] >= MAX_ERROR and uri in self.nodes_ativos:
                    self.nodes_ativos.remove(uri)
                    self._log_console(f"Removido nó inativo ({uri}) após falhas consecutivas. (saiu dos nós inscritos)")
        
    def run(self):
        heartbeat_thread = threading.Thread(target=self.heartbeat_loop, daemon=True)
        heartbeat_thread.start()

        novos_nos_thread = threading.Thread(target=self.cadastra_novos_nos, args=(self.ns,), daemon=True)
        novos_nos_thread.start()
        
        self.daemon.requestLoop()

    def unregister(self):
        if self.ns:
            self.ns.remove(self.nome)
            self._log("Removido do NameServer (saiu dos nós inscritos no Pyro).")
    
            self.daemon.shutdown()
            self.daemon.close()
            self._log("Daemon encerrado.")
    
    def heartbeat_loop(self):
        while True:
            try:
                self.gerencia_heartbeat()
            except Exception as e:
                self._log_console(f"Erro no heartbeat: {e}")
                time.sleep(1) 

    def cadastra_novos_nos(self, ns):
        while True:
            ns._pyroClaimOwnership()
            lista = ns.list()
                
            for e in lista:
                if str(e) != "Pyro.NameServer" and e != self.nome:
                    uri_str = str(lista[e])
                    if uri_str not in self.nodes_ativos:
                        self._log_console(f"Descobrindo novo nó {e} com URI {lista[e]}")
                        self.nodes_ativos.append(uri_str)
                        self._log_console(f"Nó {e} adicionado à lista de ativos. Total: {len(self.nodes_ativos)}")
            
            time.sleep(3)

if __name__ == "__main__":
    ns = locate_ns()
    n = Node(args)
    ns.register(f"{n.nome}", n.uri)
    n.ns = ns

    root = tk.Tk()
    app = NodeGUI(root, node=n)
    root.mainloop()
