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
    def __init__(self,args):
        self.nome = args.name
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
        #inicializando mensagem e contador de respostas positivas
        self.estado = WANTED
        mensagem = (tempo,uri)
        count = 0

        while count < len(self.nodes_ativos) -1:
            for e in self.nodes_ativos:
                if(e.ceder_acesso(mensagem)):
                    count += 1

        self.estado = HELD
        # Iniciar timer para liberar automaticamente após MAX_ACCESS_TIME
        self.timer = threading.Timer(MAX_ACCESS_TIME, self.liberar_acesso)
        self.timer.start()
        return
    
    @expose
    @oneway
    def ceder_acesso(self,mensagem):
        if self.estado == RELEASED:
            return True
        else:
            self.fila_pedidos.put(mensagem)
            
    def liberar_acesso(self):
        print(f"Nó {self.nome} liberando acesso automaticamente após {MAX_ACCESS_TIME} segundos.")
        self.estado = RELEASED
        # O estado agora é RELEASED, permitindo que outros nós adquiram acesso
        self.timer = None
        
    @expose
    @oneway
    def enviar_heartbeat(self):
        # oneway: não retorna valor; apenas registra que recebeu
        print(f"Heartbeat recebido em {self.nome}")
        return
        
    def gerencia_heartbeat(self):
        
        time.sleep(2)
        print("Dormindo...")

        nodes_copia = list(self.nodes_ativos)
        print("Iniciando gerenciamento de heartbeats...")
        for e in nodes_copia:
            print(f"Enviando heartbeat para nó com URI: {getattr(e, '_pyroUri', 'desconhecido')}")
            try:
                # Timeout curto para não travar
                # Proxies do Pyro não são thread-safe: reclamar a posse neste thread
                try:
                    e._pyroClaimOwnership()
                except Exception:
                    # se não suportar (ou já for nosso), segue
                    pass
                e._pyroTimeout = 2.0
                e.enviar_heartbeat()
                # sucesso: zera contador de falhas
                key = str(getattr(e, "_pyroUri", "desconhecido"))
                self._hb_failures[key] = 0
            except Exception as ex:
                key = str(getattr(e, "_pyroUri", "desconhecido"))
                self._hb_failures[key] = self._hb_failures.get(key, 0) + 1
                print(f"Nó não respondeu ao heartbeat ({key}) [falhas={self._hb_failures[key]}]: {type(ex).__name__}: {ex}")
                # remove após 3 falhas consecutivas
                if self._hb_failures[key] >= 3 and e in self.nodes_ativos:
                    try:
                        e._pyroRelease()
                    except Exception:
                        pass
                    self.nodes_ativos.remove(e)
                    print(f"Removido nó inativo ({key}) após falhas consecutivas.")
    
    def gerenciar_acesso(self):
        #while temporizador != tempo_limite:
        return 1
        
    def run(self):
        heartbeat_thread = threading.Thread(target=self.heartbeat_loop, daemon=True)
        heartbeat_thread.start()

        novos_nos_thread = threading.Thread(target=self.cadastra_novos_nos,args=self.ns, daemon=True)
        novos_nos_thread.start()
        
        self.daemon.requestLoop()
    
    def heartbeat_loop(self):
        while True:
            try:
                self.gerencia_heartbeat()
            except Exception as e:
                print(f"Erro no heartbeat: {e}")
                time.sleep(1) 

    def cadastra_novos_nos(self,ns):
        while True:
            lista = ns.list()
            for e in lista:
                if str(e) != "Pyro.NameServer" and  e != self.nome:
                    print(f"Cadastrando o proxy do nó {e} que tem uri {lista[e]}")
                    proxy_no_ativo = Proxy(lista[e])
                    # tenta bind imediato e configura timeout
                    try:
                        proxy_no_ativo._pyroBind()
                        proxy_no_ativo._pyroTimeout = 2.0
                    except Exception as ex:
                        print(f"Falha ao conectar ao nó {e} ({lista[e]}): {type(ex).__name__}: {ex}")
                        continue
                    self.nodes_ativos.append(proxy_no_ativo)

    
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


ns = ensure_nameserver(host="127.0.0.1", port=9090)
n = Node(args)
n.ns = ns
ns.register(f"{n.nome}", n.uri) 

# Adicionar logs detalhados para depuração
print(f"Registrando nó {n.nome} com URI {n.uri}")

# Verificar se todos os peers estão sendo adicionados corretamente
print("Lista de nós registrados no NameServer:")
lista = ns.list()
for e in lista:
    print(f"Nó: {e}, URI: {lista[e]}")

print(n.nome)
n.run()