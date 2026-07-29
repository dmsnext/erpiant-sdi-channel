{
    "name": "Erpiant SDI Channel",
    "summary": "Canale SDI esclusivo Erpiant: fatturazione elettronica via broker "
    "AWS erpiant.com ↔ Invoicetronic, in modalità pay-per-use",
    "version": "16.0.1.0.0",
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
