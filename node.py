from apscheduler.schedulers.background import BackgroundScheduler
import argparse
from gui import NodeGUI
from Pyro5.api import expose,Proxy,oneway, locate_ns, Daemon
import textwrap
import threading
import time
import tkinter as tk

RELEASED = 0
WANTED = 1 
HELD = 2

MAX_ACCESS_TIME = 20
REQUEST_TIMEOUT = 2.0
RESPONSE_TIMEOUT = 2.0
# MAX_ERROR = 3
HEARTBEAT_INTERVAL = 10
HEARTBEAT_CHECK = 15

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
        self.fila_pedidos = list()
        self.timer = None
#       self.num_falhas_heartbeat = {}
        self.ns = 0
        self._log_callback = None
        self.tempo_pedido = None
        self.respostas_positivas_atual = 0
        self.ultimo_heartbeat = {}
        self.respostas_positivas = {}

        self.scheduler = BackgroundScheduler()
        self.scheduler.add_job(self.envia_heartbeat, 'interval', seconds=HEARTBEAT_INTERVAL)
        self.scheduler.add_job(self.checa_heartbeats, 'interval', seconds=HEARTBEAT_CHECK)
        self.scheduler.start()

    def envia_heartbeat(self):
        for uri in self.nodes_ativos:
            try:
                peer = Proxy(uri)
                peer._pyroClaimOwnership()
                peer._pyroBind()               
                peer.recebe_heartbeat(self.uri)
            except Exception as e:
                print(f"[{self.nome}] Falha ao enviar heartbeat para {uri}. \n Motivo {e}.")
                # Remove o nó inativo, ultimo heartbeat dele e checa se pode entrar na SC
                self.nodes_ativos.remove(uri)
                self.ultimo_heartbeat.pop(uri, None)
                self.verifica_resposta()

    @expose
    @oneway
    def recebe_heartbeat(self, uri):
        self.ultimo_heartbeat[uri] = time.time()

    def checa_heartbeats(self):
        agora = time.time()
        remove_peers = False
        # percorre todos os peers registrados
        for uri, ultimo in list(self.ultimo_heartbeat.items()):
            # se o nó não respondeu em tempo suficiente, marca pra remoção
            if (uri in self.nodes_ativos) and agora - ultimo > (HEARTBEAT_INTERVAL * 2):
                self.nodes_ativos.remove(uri)
                # remove o ultimo heartbeat do peer que foi excluído
                self.ultimo_heartbeat.pop(uri, None)
                remove_peers = True

        if remove_peers:
            self.verifica_resposta()

    def verifica_resposta(self):
        if self.estado == WANTED and self.respostas_positivas_atual == len(self.nodes_ativos):
            self.estado = HELD
            self._log(f"ENTROU na seção crítica (todas as respostas positivas: {self.respostas_positivas_atual}/{len(self.nodes_ativos)}). Agora COM ACESSO ao recurso.")

            self.timer = threading.Timer(MAX_ACCESS_TIME, self.liberar_acesso)
            self.timer.daemon = True
            self.timer.start()
                
            return True
        else:
            return False

         
    def pedir_acesso(self,tempo,uri):
        if self.tempo_pedido is None:
            self.tempo_pedido = tempo
        self.estado = WANTED
        mensagem = (self.tempo_pedido, uri)

#       total_esperado = 0
        self.respostas_positivas_atual = 0

        for uri in self.nodes_ativos: #percorre lista de nós ativos e pede acesso
            proxy = None
            #timeout_original = None
            try:
                proxy = Proxy(uri)
                proxy._pyroClaimOwnership()
                #timeout_original = proxy._pyroTimeout
                proxy._pyroTimeout = REQUEST_TIMEOUT

                concedeu = bool(proxy.ceder_acesso(mensagem))
                #total_esperado += 1
                if concedeu:
                    self.respostas_positivas_atual += 1
 #              key = proxy._pyroUri
 #              self.num_falhas_heartbeat[key] = 0
            except Exception as ex:
                self._log_console(f"Timeout/erro aguardando resposta. Removendo nó. Motivo: {type(ex).__name__}: {ex}")
                if proxy is not None:
                    proxy._pyroRelease()
                if uri in self.nodes_ativos:
                    # remove peer e ultimo heartbeat dele
                    self.nodes_ativos.remove(uri)
                    self.ultimo_heartbeat.pop(uri, None)
#       self._log_console('estou preso')
        self.verifica_resposta()
            

    @expose
    def ceder_acesso(self,mensagem):
        if self.estado == RELEASED:
            req_ts, req_uri = mensagem
            self._log_console(f"Concedendo acesso para pedido de {req_uri} (ts={req_ts}).")
            return True
        elif self.estado == HELD:
            # Não pode conceder agora, enfileira
            self.fila_pedidos.append(mensagem)
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
                self.fila_pedidos.append(mensagem)
                self._log_console(f"Deferindo (WANTED) para {other_id} ts={req_ts} (meu ts={my_ts}). Pedido enfileirado.")
                return False
            
    def liberar_acesso(self):
        if self.estado != HELD:
            return
        if self.timer:
            self.tempo_pedido = None
            self.timer = None

        self._log(f"Liberando/Perdendo acesso ao recurso (timeout {MAX_ACCESS_TIME}s atingido).")
        self.estado = RELEASED
        
        pedidos = self.fila_pedidos.copy()
        for tempo, uri in pedidos:
            self.notificar_resposta(uri)
        # limpando, pois já respondeu para todos
        self.fila_pedidos.clear()
        pedidos.clear()


    def notificar_resposta(self, uri):
        try:
            proxy = Proxy(uri)
            proxy._pyroClaimOwnership()
            proxy._pyroBind()
            #timeout_original = proxy._pyroTimeout
            proxy._pyroTimeout = REQUEST_TIMEOUT
#           proxy.notificar_liberacao(self.nome, str(self.uri) )
            proxy.notificar_liberacao(self.nome)
        except Exception as ex:
            key = uri
            self._log_console(f"Falha ao notificar resposta deferida para {key}: {type(ex).__name__}: {ex}")
            for uri_ativo in list(self.nodes_ativos):
                if uri_ativo == key:
                    self.nodes_ativos.remove(uri_ativo)
                    break

    @expose
    @oneway
#   def notificar_liberacao(self, remetente_nome, uri):
    def notificar_liberacao(self, remetente_nome):
        if self.estado != HELD:
            self.respostas_positivas_atual += 1
            self._log_console(f"Notificação de liberação recebida de {remetente_nome}. Reavaliando pedido...")
            self.verifica_resposta()
        return
    
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
        
    def run(self):

        novos_nos_thread = threading.Thread(target=self.cadastra_novos_nos, args=(self.ns,), daemon=True)
        novos_nos_thread.start()
        self.daemon.requestLoop()

    def cadastra_novos_nos(self, ns):
        while True:
            ns._pyroClaimOwnership()
            lista = ns.list()
                
            for e in lista:
                if str(e) != "Pyro.NameServer" and e != self.nome:
#                   uri_str = str(lista[e])
                    uri = lista[e]
#                   if uri_str not in self.nodes_ativos:
                    if uri not in self.nodes_ativos:
                        self._log_console(f"Descobrindo novo nó {e} com URI {lista[e]}")
#                       self.nodes_ativos.append(uri_str)
                        # mudei aqui tbm
                        self.nodes_ativos.append(uri)
                        self._log_console(f"Nó {e} adicionado à lista de ativos. Total: {len(self.nodes_ativos)}")
            
            time.sleep(3)


    def unregister(self):
        self.ns = locate_ns()
        self.ns.remove(self.nome)
        self._log_console("Removido do NameServer (saiu dos nós inscritos no Pyro).")

        self.daemon.shutdown()
        self.daemon.close()
        self._log_console("Daemon encerrado.")

if __name__ == "__main__":
    ns = locate_ns()
    n = Node(args)
    ns.register(f"{n.nome}", n.uri)
    n.ns = ns

    root = tk.Tk()
    app = NodeGUI(root, node=n)
    root.mainloop()

# comentei essas abaixo porque não estão usando
    
#    def heartbeat_loop(self):
#        while True:
#            try:
#                self.gerencia_heartbeat()
#            except Exception as e:
#                self._log_console(f"Erro no heartbeat: {e}")
#                time.sleep(1) 

#  def entra_sc(self):
#     print(f"[{self.nome}] Entrou na seção crítica.")
#     self.estado = HELD

    

# def gerencia_heartbeat(self):
#           time.sleep(2)
#           self._log_console("Dormindo...")
#           self._log_console(f"Nós ativos -> {len(self.nodes_ativos)}\n Respostas Positivas:{self.respostas_positivas_atual} ")

#           nodes_copia = list(self.nodes_ativos)
#           for uri in nodes_copia:
#               self._log_console(f"Enviando heartbeat para nó com URI: {uri}")
#               try:
#                   p = Proxy(uri)
#                   p._pyroClaimOwnership()

#                   p._pyroTimeout = RESPONSE_TIMEOUT
#                   p.enviar_heartbeat()
#                   self.num_falhas_heartbeat[uri] = 0

#               except Exception as ex:
#                   self.num_falhas_heartbeat[uri] = self.num_falhas_heartbeat.get(uri, 0) + 1
#                   self._log_console(f"Nó não respondeu ao heartbeat ({uri}) [falhas={self.num_falhas_heartbeat[uri]}]: {type(ex).__name__}: {ex}")

#                  if self.num_falhas_heartbeat[uri] >= MAX_ERROR and uri in self.nodes_ativos:
#                      self.nodes_ativos.remove(uri)
#                      self._log_console(f"Removido nó inativo ({uri}) após falhas consecutivas. (saiu dos nós inscritos)")

#   @expose
#   @oneway
#   def enviar_heartbeat(self):
#       self._log_console("Heartbeat recebido.")
#       return
