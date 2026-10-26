# Design, notater


Kan implementere gates som en Gate klasse
som har en predikatfunksjon knyttet til seg. (virtuel / abstrakt klasse?)

```python
class Gate:
    def __init__(self, expression):
        self._expression = expression

    def evaluate(x: bool, y: bool) -> bool:
        return self._expression(x,y)

and_gate = Gate(lambda x, y: x and y)
```

evaluering kan da skje for hver gate i en krets. 
Hvordan designe en graf?
Kan sette dette opp som en graf som en node:

```python
class Node:
    def __init__(self, gate: Gate):
        self._gate = gate
        self._next: list[Gate] = list()
    
```

Vi kan da gjøre et breddeevaluering gjennom grafen for å evaluere kretsen. 



