# Copyright 2026 DMSNEXT
# License AGPL-3.0 or later (https://www.gnu.org/licenses/agpl).
"""Guardia sull'indirizzo prima di generare la FatturaPA.

Il template di export emette ``<Sede>`` **senza alcun ``t-if``** sia per il
cedente sia per il cessionario, e dentro ``<Indirizzo>``, ``<Comune>``,
``<Nazione>`` e ``<Provincia>`` escono dai campi del partner **senza fallback**
(solo il ``<CAP>`` ripiega su ``00000``) — cfr.
``l10n_it_fatturapa_out/data/invoice_it_template.xml:230-258``.

Due precisazioni importanti su **cosa è già coperto a monte**, verificate sul
codice il 2026-10-07 per non duplicare controlli esistenti:

1. ``l10n_it_fatturapa/models/partner.py:_check_ftpa_partner_data`` **valida già**
   via, CAP, città e nazione — ma **solo** sui partner con
   ``electronic_invoice_subjected``, e scatta al salvataggio dell'anagrafica.
   Il **cliente** è quindi già protetto, e in modo più severo (pretende anche il
   CAP). Qui non si ripete.
2. Restano scoperti **due casi**, ed è di quelli che si occupa questa guardia:

   * **la sede dell'azienda emittente**: il vincolo di monte è gated su
     ``electronic_invoice_subjected``, che è un flag del *cliente*; l'anagrafica
     della propria azienda normalmente non ce l'ha ⇒ **non viene mai
     controllata**. È esattamente il caso della microimpresa appena registrata
     che emette la sua prima fattura.
   * **la provincia**: ``state_id`` compare nel decoratore ``@api.constrains``
     di monte ma **nel corpo non viene mai verificato** — una svista a monte.
     Eppure ``<Provincia>`` è obbligatorio per l'Italia e non ha ripiego.

``preventive_checks()`` di monte, dal canto suo, controlla tipo documento,
termini di pagamento, imposte sulle righe e coerenza della partita IVA
aziendale, **ma nulla dell'indirizzo**.
"""

from odoo import _, models
from odoo.exceptions import UserError

#: Campi che finiscono in ``<Sede>`` senza valore di ripiego. Applicati per
#: intero alla sola azienda emittente: sul cliente ci pensa già
#: ``_check_ftpa_partner_data`` (vedi docstring del modulo).
SEDE_REQUIRED_FIELDS = [
    ("street", "l'indirizzo (via e numero civico)"),
    ("city", "la città"),
    ("country_id", "la nazione"),
]


class AccountMove(models.Model):
    _inherit = "account.move"

    @staticmethod
    def _erpiant_missing_province(partner):
        """``<Provincia>`` esce solo per l'Italia, e anche lì senza ripiego."""
        if partner.country_id.code == "IT" and not partner.state_id:
            return ["la provincia"]
        return []

    @classmethod
    def _erpiant_missing_sede_fields(cls, partner):
        """Elenco leggibile di ciò che manca al partner per la ``<Sede>``."""
        missing = [label for name, label in SEDE_REQUIRED_FIELDS if not partner[name]]
        return missing + cls._erpiant_missing_province(partner)

    def preventive_checks(self):
        res = super().preventive_checks()
        for invoice in self:
            # Se il cliente non è soggetto a fattura elettronica non viene
            # generato alcun XML: bloccare l'utente sarebbe solo un intralcio.
            if not invoice.partner_id.electronic_invoice_subjected:
                continue

            problems = []
            company_partner = invoice.company_id.partner_id
            missing_company = self._erpiant_missing_sede_fields(company_partner)
            if missing_company:
                problems.append(
                    _(
                        "Della tua azienda (%(name)s) manca: %(fields)s.\n"
                        "Puoi completarlo in: Opzioni → Impostazioni generali → Aziende."
                    )
                    % {
                        "name": company_partner.display_name,
                        "fields": ", ".join(missing_company),
                    }
                )

            # Del cliente si verifica la SOLA provincia: via, CAP, città e
            # nazione sono già pretese da `_check_ftpa_partner_data` al
            # salvataggio dell'anagrafica, e ripeterle qui sarebbe codice morto.
            missing_partner = self._erpiant_missing_province(invoice.partner_id)
            if missing_partner:
                problems.append(
                    _(
                        'Del cliente "%(name)s" manca: %(fields)s.\n'
                        "Puoi completarlo in: Contabilità → Clienti."
                    )
                    % {
                        "name": invoice.partner_id.display_name,
                        "fields": ", ".join(missing_partner),
                    }
                )

            if problems:
                raise UserError(
                    _(
                        "Prima di emettere la fattura elettronica %(invoice)s devi "
                        "completare l'indirizzo.\n\n%(problems)s\n\n"
                        "Senza questi dati il file verrebbe generato lo stesso, ma il "
                        "Sistema di Interscambio lo scarterebbe a fattura già emessa e "
                        "non più modificabile."
                    )
                    % {
                        "invoice": invoice.name or "",
                        "problems": "\n\n".join(problems),
                    }
                )
        return res
