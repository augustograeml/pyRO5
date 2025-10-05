import argparse
import textwrap
import threading
from Pyro5.api import *
import time
from queue import Queue
import json

RELEASED = 0
WANTED = 1 
HELD = 2


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
        self.daemon = Daemon()
        self.uri = self.daemon.register(self)
        self.nodes_ativos = []
        self.fila_pedidos = Queue()
    
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
        return
    
    @expose
    @oneway
    def ceder_acesso(self,mensagem):
        if self.estado == RELEASED:
            return True
        else:
            self.fila_pedidos.put(mensagem)

    @expose
    @oneway
    def enviar_heartbeat(self):
        print("Heartbeat enviado")
        return True
        
    def gerencia_heartbeat(self):
        
        time.sleep(2)
        print("Dormindo...")

        nodes_copia = self.nodes_ativos
        for e in nodes_copia:
            try:
                e.enviar_heartbeat()
            except:
                print(f"Nó não respondeu ao heartbeat, removendo...")
                if e in self.nodes_ativos:
                    self.nodes_ativos.remove(e)
    
    def gerenciar_acesso(self):
        #while temporizador != tempo_limite:
        return 1
        
    def run(self):
        heartbeat_thread = threading.Thread(target=self.heartbeat_loop, daemon=True)
        heartbeat_thread.start()
        
        self.daemon.requestLoop()
    
    def heartbeat_loop(self):
        while True:
            try:
                self.gerencia_heartbeat()
            except Exception as e:
                print(f"Erro no heartbeat: {e}")
                time.sleep(1) 

    
ns = locate_ns()          
n = Node(args)

ns.register(f"{n.nome}", n.uri) 

lista = ns.list()

for e in lista:
    if str(e) != "Pyro.NameServer":
        print(f"Cadastrando o proxy do nó {e} que tem uri {lista[e]}")
        proxy_no_ativo = Proxy(lista[e])
        n.nodes_ativos.append(proxy_no_ativo)

print(n.nome)
print(f"Os proxys dos nos ativos {n.nodes_ativos}")
for e in n.nodes_ativos:
    e.enviar_heartbeat()
n.run()  



