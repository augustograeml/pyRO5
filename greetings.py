import Pyro5.api

@Pyro5.api.expose
class GreetingMaker(object):
    def get_name(self, name):
        return f"Hello my name is {name} Graeml!"
@Pyro5.api.expose
class Classe2(object):
    def get_name(self, name):
        return f"Hello my name is {name} Pavesi Moretti!"

daemon = Pyro5.server.Daemon()         # make a Pyro daemon
ns = Pyro5.api.locate_ns()             # find the name server
uri = daemon.register(GreetingMaker) 
uri2 = daemon.register(Classe2)  # register the greeting maker as a Pyro object
ns.register("example.greeting", uri)
ns.register("example.classe", uri2)   # register the object with a name in the name server

print("Ready.")
daemon.requestLoop()     