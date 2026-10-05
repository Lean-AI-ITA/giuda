# Sicurezza

## Modello di sicurezza

- Giuda ascolta solo su `127.0.0.1` e rifiuta le richieste POST con `Origin` diverso da `localhost`/`127.0.0.1`.
- Non esegue il codice dei repository: legge solo i diff tramite le API di GitHub.
- Chiavi API e token GitHub sono salvati in chiaro in `data/config.json`. La cartella è esclusa da Git tramite `.gitignore`. L'interfaccia mostra solo le ultime 4 cifre.

## Raccomandazioni

- Usa un token GitHub **fine-grained**, limitato ai soli repository da sorvegliare, con permesso **Contents: Read-only**. Concedi *Read and write* solo se attivi la pubblicazione dei commenti.
- Per codice riservato o con dati personali usa un **modello locale**: con un'API il diff viene inviato al fornitore.
- Non esporre la porta 8765 su altre interfacce di rete.

## Segnalare una vulnerabilità

Non aprire una issue pubblica. Usa **Security → Report a vulnerability** sul repository GitHub (segnalazione privata).
