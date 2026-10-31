{
    "name": "Erpiant SDI Channel",
    "summary": "Canale SDI esclusivo Erpiant: fatturazione elettronica via broker "
    "AWS erpiant.com ↔ Invoicetronic, in modalità pay-per-use",
    # ⚠️ 16.0.1.0.0 → 16.0.1.3.0 in un colpo solo: i tre commit che hanno aggiunto campi
    # al modello (`632f578` attivazione con numero di licenza, `59d4e5f` scambio
    # licenza→credenziale, `760e3d6` precompilazione anagrafica) NON avevano alzato la
    # versione. Su un tenant dove il modulo è già installato, Odoo decide se aggiornare
    # confrontando questa stringa con `ir_module_module.latest_version`: a parità, lo
    # SALTA — e le colonne nuove non vengono create. Sintomo osservato il 2026-10-09:
    # `psycopg2.errors.UndefinedColumn: column sdi_channel.erpiant_license_code does not
    # exist` aprendo le Impostazioni. Ogni commit che tocca i campi deve alzarla.
    # ⚠️ 16.0.1.3.0 → 16.0.1.4.0: il menu dei canali torna sotto Configurazione →
    # Contabilità, il menuitem senza parent lo aveva portato fra le applicazioni.
    "version": "16.0.1.4.0",
    "category": "Accounting/Localizations/EDI",
    "author": "DMSNEXT",
    "website": "https://erpiant.com",
    "license": "AGPL-3",
    "depends": [
        "l10n_it_fatturapa_out",
        "l10n_it_fatturapa_in",
        "l10n_it_sdi_channel",
    ],
    "external_dependencies": {
        "python": ["requests"],
    },
    "data": [
        "security/erpiant_sdi_security.xml",
        "security/ir.model.access.csv",
        "data/ir_cron.xml",
        "views/sdi_channel_views.xml",
        "views/res_config_settings_views.xml",
    ],
    "post_init_hook": "post_init_hook",
    "installable": True,
    "application": False,
    "auto_install": False,
}
