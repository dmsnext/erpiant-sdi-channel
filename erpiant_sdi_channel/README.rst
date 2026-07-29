===================
Erpiant SDI Channel
===================

Canale SDI **esclusivo Erpiant** per la fatturazione elettronica dei micro
imprenditori italiani, in modalità pay-per-use.

Il modulo aggiunge il tipo di canale ``erpiant_aws`` al framework OCA
``l10n_it_sdi_channel`` e inoltra le fatture elettroniche al **broker SDI di
erpiant.com** (architettura AWS, repo ``erpiant-aws``), che a sua volta si
interconnette al fornitore **Invoicetronic**, intermediario verso lo SdI
dell'Agenzia delle Entrate.

La API Key Invoicetronic **non risiede mai nel tenant**: vive solo nel broker
(AWS SSM Parameter Store). Il tenant si autentica al broker con un token
dedicato.

Esclusività del fornitore (lock-down)
=====================================

Il tenant può usare **esclusivamente** il servizio Erpiant. Abilitare un
fornitore diverso richiede una **modifica del codice** (cfr.
``doc/ARCHITETTURA_erpiant_sdi_channel.md`` §7.7): costante ``ERPIANT_SDI_LOCKDOWN``,
``@api.constrains`` sul ``channel_type``, UI senza selettore fornitore, ACL che
riservano la gestione canali a un gruppo tecnico non assegnato.

Ambienti
========

Il campo *Ambiente* (``test`` / ``live``) determina quale chiave usa il broker
(``ik_test_…`` / ``ik_live_…``). In sviluppo usare sempre ``test`` (sandbox).

Documentazione completa
=======================

La documentazione operativa del servizio SDI (broker AWS + questo modulo),
riscritta per un sysops, è consolidata nel repo ``erpiant-16-website`` in
``doc/SDI/`` (indice in ``00-README.md``): architettura, runbook di deploy,
provisioning, webhook, glossario.
