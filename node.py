import argparse
import textwrap
import threading
from Pyro5.api import *
import time

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
    
    def pedir_acesso(tempo,uri):
        messagem = (tempo,uri)
        return
    
    @expose
    @oneway
    def ceder_acesso(self):
        if self.estado == RELEASED:
            return True
        else:
            return False

    @oneway
    def enviar_heartbeat():
        print("Heartbeat enviado")
        return True
        
    def gerencia_heartbeat(self):
        
        time.sleep(2)

        for e in self.nodes_ativos:
            try:
                a = e.proxy(e.uri)
                a.enviar_heartbeat()
            except:
                self.nodes_ativos.remove(e)
    
    def gerenciar_acesso(self):
        return "hello"

    def run(self):
        while True:
            try:
                self.gerencia_heartbeat()
            except:
                print("Erro ao rodar!")

    
ns = locate_ns()          
n = Node(args)
ns.register(f"{n.nome}", n.uri) 
n.nodes_ativos = ns.list()

print(n.nome)
print(f"Os nodes ativos {n.nodes_ativos}")
n.run()
n.daemon.requestLoop()  


