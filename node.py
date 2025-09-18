import argparse
import textwrap
import threading
from Pyro5.api import *

RELEASED = 0
WANTED = 1 
HELD = 2

# TODO 
# TODO 
# TODO 
# TODO 

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


class Node:
    def __init__(self,args):
        self.nome = args.name
        self.estado = RELEASED
    
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
        hello = args    
        return
    
    def run(self):
        try:
            while True:
                self.enviar_heartbeat()
        except:
            print()

n = Node(args)

daemon = Daemon()             # make a Pyro daemon
uri = daemon.register(Node)    # register the greeting maker as a Pyro object

print("Ready. Object uri =", uri)       # print the uri so we can use it in the client later
daemon.requestLoop()  

print(n.nome)
