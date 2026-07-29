# erpiant_sdi_channel

Canale SDI per **Odoo 16**: trasmette e riceve fatture elettroniche italiane
attraverso il broker di [ERPIANT](https://www.erpiant.com), in modalità
pay-per-use.

Il modulo aggiunge il tipo di canale `erpiant_aws` al framework OCA
`l10n_it_sdi_channel` e inoltra i documenti al broker ERPIANT, che si
interconnette a un intermediario accreditato verso lo SdI dell'Agenzia delle
Entrate. Le credenziali dell'intermediario **non risiedono mai nel tenant**: il
tenant si autentica al broker con un proprio token.

## Perché questo repository esiste

Questo modulo è rilasciato sotto **AGPL-3.0** ed è distribuito all'interno del
prodotto ERPIANT. La licenza dà a chi riceve il programma il diritto di
ottenerne il codice sorgente corrispondente: **questo repository è quel
sorgente**, ed è pubblico per assolvere a tale obbligo.

> **Avviso AGPL v3, art. 13** — se rendete le funzioni di questo modulo
> accessibili a terzi attraverso una rete, siete tenuti a offrire a quegli utenti
> il codice sorgente corrispondente. Potete assolvere all'obbligo indicando loro
> l'indirizzo di questo repository.

## Cosa NON c'è qui

ERPIANT comprende anche componenti **proprietarie** — l'interfaccia utente, il
programma di installazione, la procedura di build e il database precompilato —
che non sono software libero, non sono coperte da alcuna offerta del sorgente e
non sono incluse in questo repository. L'elenco completo dei componenti del
prodotto e delle rispettive licenze è nel file `NOTICE.txt` distribuito con
ERPIANT e alla pagina <https://www.erpiant.com/open-source>.

Il repository parte da un **import senza storia**: contiene il codice come
distribuito, non la cronologia interna di sviluppo.

## Requisiti

- Odoo 16.0
- OCA [`l10n-italy`](https://github.com/OCA/l10n-italy): `l10n_it_fatturapa_out`,
  `l10n_it_fatturapa_in`, `l10n_it_sdi_channel`
- Python: `requests`

## Installazione

Copiare la directory `erpiant_sdi_channel/` in un percorso dell'`addons_path` di
Odoo, aggiornare l'elenco delle applicazioni e installare il modulo. La
configurazione del canale (endpoint del broker, ambiente, token) si trova in
_Contabilità → Configurazione → Canali SDI_.

## Licenza

AGPL-3.0 — vedere il file [`LICENSE`](LICENSE).
Copyright (c) 2026 Alessandro Ronda.

Richieste relative a licenze e sorgenti: <info@dmsnext.com>
