# Contre-épreuves par mutation — Sécurité — search_path des fonctions SECURITY DEFINER (suite de P2.11) (exécution du 12/10/2026 22:39 UTC)

Rapport généré par `scripts/mutation_check.py`. Il décrit une exécution réelle ; les résultats
historiques ne sont pas recopiés ici.

- **Catalogue** : `scripts/mutations/sec_search_path.json`
- **Code** : commit interne (identifiant retiré de cette version publique) avec modifications non commitées
- **Environnement** : projet Docker jetable `rbi-mut`, base de test pytest-django, détruit en fin d'exécution ; volumes de développement inchangés
- **Référence sans mutation** : tests détecteurs réussis (code 0)

| Réf. | Origine | Contrôle | Détecteurs attendus | Détecteurs en échec (observé) | Verdict | Restauration |
|---|---|---|---|---|---|---|
| SP-01 | nouvelle | pg_temp placé en dernier dans le search_path des huit fonctions | `test_a_temporary_chain_head_does_not_divert_the_audit_seal`<br>`test_every_security_definer_function_puts_pg_temp_last`<br>`test_temporary_tables_do_not_allow_resetting_another_accounts_mfa`<br>`test_temporary_tables_do_not_change_the_organisation_of_the_current_account`<br>`test_temporary_tables_do_not_fool_the_organisation_audit_reader`<br>`test_temporary_tables_do_not_fool_the_platform_audit_reader` | `test_a_temporary_chain_head_does_not_divert_the_audit_seal`<br>`test_every_security_definer_function_puts_pg_temp_last`<br>`test_temporary_tables_do_not_allow_resetting_another_accounts_mfa`<br>`test_temporary_tables_do_not_change_the_organisation_of_the_current_account`<br>`test_temporary_tables_do_not_fool_the_organisation_audit_reader`<br>`test_temporary_tables_do_not_fool_the_platform_audit_reader` | **détectée** | identique |
| SP-02 | nouvelle | Fonction du déclencheur d'audit couverte par la migration | `test_a_temporary_chain_head_does_not_divert_the_audit_seal`<br>`test_every_security_definer_function_puts_pg_temp_last` | `test_a_temporary_chain_head_does_not_divert_the_audit_seal`<br>`test_every_security_definer_function_puts_pg_temp_last` | **détectée** | identique |
| SP-03 | nouvelle | Fonction d'écriture rbi_admin_reset_mfa couverte par la migration | `test_every_security_definer_function_puts_pg_temp_last`<br>`test_temporary_tables_do_not_allow_resetting_another_accounts_mfa` | `test_every_security_definer_function_puts_pg_temp_last`<br>`test_temporary_tables_do_not_allow_resetting_another_accounts_mfa` | **détectée** | identique |

Empreintes finales identiques à l'état initial : `backend/apps/core/migrations/0003_definer_search_path.py` oui
