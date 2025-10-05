# saved as greeting-client.py
import Pyro5.api

name = input("What is your name? ").strip()

ns = Pyro5.api.locate_ns()
greeting_maker = ns.list()  # use name server object lookup uri shortcut]
for e in greeting_maker:
    if(e != "Pyro.NameServer"):
        proxy = Pyro5.api.Proxy(greeting_maker[e])
        print(proxy.get_name(name))