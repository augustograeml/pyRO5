Sistema Distribuído com Pyro5

Descrição rápida

- Implementa pedidos de acesso à seção crítica entre nós P2P usando Pyro5.
- Cada pedido espera respostas de todos os nós ativos com timeout. Se algum nó não responder a tempo, é considerado inativo e removido da lista de nós ativos.
- O receptor SEMPRE responde ao pedido: concede (True) se estiver RELEASED, ou nega (False) e enfileira o pedido.
- Ao entrar na seção crítica, um temporizador libera automaticamente o acesso após 10s (MAX_ACCESS_TIME).

Como executar (linha de comando)

1. Instale dependências (veja requirements.txt).
2. Em terminais separados, suba 2+ nós, por exemplo:
   - powershell 1:
     python node.py -n PeerA
   - powershell 2:
     python node.py -n PeerB

Observações

- O sistema inicia/usa um NameServer Pyro5 local em 127.0.0.1:9090 se não encontrar um.
- Cada pedido de acesso usa timeout de REQUEST_TIMEOUT (2s) por nó. Falhas/timeout removem o nó da lista.
- O heartbeat também roda em background para remoção de nós inativos após falhas consecutivas.

GUI opcional (experimento)

- Você pode iniciar a interface gráfica com:
  python gui.py
- Informe o nome do nó e clique em "Iniciar Nó". Use "Pedir Acesso" para solicitar a seção crítica.

Parâmetros importantes

- MAX_ACCESS_TIME: 10s (tempo máximo segurando a seção crítica)
- REQUEST_TIMEOUT: 2s (tempo de espera por resposta de cada nó)

Créditos

- Trabalho acadêmico para a disciplina de Sistemas Distribuídos.
