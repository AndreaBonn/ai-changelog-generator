[English](SECURITY.md) | **Italiano**

# Policy di sicurezza

## Versioni supportate

| Versione | Supportata |
|---|---|
| 1.x | Sì |

## Segnalare una vulnerabilità

Per segnalare una vulnerabilità di sicurezza, usa [GitHub Security Advisories](https://github.com/AndreaBonn/ai-changelog-generator/security/advisories/new). Non aprire una issue pubblica.

Includi nella segnalazione:

- Descrizione della vulnerabilità
- Passaggi per riprodurla
- Versione/i interessate
- Impatto potenziale

Tempi di risposta:

- Presa in carico entro 72 ore
- Fix per vulnerabilità critiche entro 30 giorni
- Disclosure pubblica coordinata dopo il rilascio del fix

## Misure di sicurezza

Questo progetto implementa le seguenti pratiche di sicurezza verificabili:

- **API key trasmesse via header, mai negli URL**: tutti e quattro i provider LLM (Groq, Gemini, Anthropic, OpenAI) passano le API key esclusivamente tramite header HTTP (`providers.py:160-163, 175-176, 190-194, 205-208`).
- **Isolamento delle variabili d'ambiente**: tutta la configurazione è letta dalle variabili d'ambiente in una singola funzione, `Config.from_env()` (`config.py:37`). Nessun altro modulo accede a `os.environ`.
- **Nessun secret nei log**: il progetto usa esclusivamente `logging` (zero istruzioni `print()`). API key e token non sono mai inclusi nei messaggi di log.
- **Validazione input al boundary**: le variabili d'ambiente richieste sono validate all'avvio con messaggi di errore espliciti (`config.py:46-56`). I parametri interi sono validati per range (`config.py:101-128`).
- **SHA pinning sulle GitHub Actions**: tutte le action di terze parti nei workflow CI sono pinnate a SHA di commit specifici, non a tag mutabili (`action.yml:58`, `.github/workflows/test.yml:15-16`).
- **Lockfile delle dipendenze**: `uv.lock` è committato nel repository, garantendo build riproducibili.
- **Marker per commit automatici**: i commit effettuati dall'action includono `[skip ci]` per prevenire trigger CI ricorsivi (`publisher.py:45`).

## Buone pratiche di sicurezza per gli utenti

Quando configuri questa action nei tuoi workflow:

- Salva le API key come GitHub Actions secrets, mai come testo in chiaro nei file workflow.
- Usa un token GitHub con i permessi minimi necessari (`contents: write` per aggiornare le release).
- Pinna l'action a uno SHA di commit specifico o a un tag di release, non a un nome di branch.

## Fuori ambito

I seguenti casi non sono considerati vulnerabilità per questo progetto:

- Vulnerabilità in dipendenze di terze parti già pubblicamente note (vanno segnalate upstream).
- Qualità o accuratezza del contenuto del changelog generato dall'LLM.
- Esaurimento del rate limit da pattern di utilizzo normale.
- Problemi che richiedono accesso fisico all'ambiente runner.
- Attacchi di social engineering.

## Ringraziamenti

I ricercatori di sicurezza che segnalano vulnerabilità valide saranno citati qui su richiesta.

---

[Torna al README](README.it.md)
