"""Clés étrangères composites : la séparation des portées est garantie par PostgreSQL, pas seulement par le code.

- users_role_permission (role_id, role_scope)             → users_role (id, scope)
- users_role_permission (permission_id, permission_scope) → users_permission (id, scope)
  combinées au CHECK role_scope = permission_scope : un rôle d'organisme ne peut pas contenir une permission plateforme ;
- users_user_role (role_id, scope)                        → users_role (id, scope)
  combinée au CHECK portée/organisme : la portée d'une affectation est celle du rôle ;
- users_user_role (user_id, organization_id)              → users_user (id, organization_id)
  une affectation d'organisme porte l'organisme réel de l'utilisateur (MATCH SIMPLE : non vérifiée si NULL,
  cas des affectations plateforme, dont la cohérence avec un compte plateforme est assurée par les services
  et par l'évaluation des permissions).
"""

from django.db import migrations

# ON UPDATE NO ACTION (défaut) : un utilisateur ne peut pas changer d'organisme en conservant ses affectations.
FOREIGN_KEYS = (
    ("users_role_permission", "rp_role_scope_fk", "(role_id, role_scope)", "users_role (id, scope)", "CASCADE"),
    (
        "users_role_permission",
        "rp_permission_scope_fk",
        "(permission_id, permission_scope)",
        "users_permission (id, scope)",
        "CASCADE",
    ),
    ("users_user_role", "ur_role_scope_fk", "(role_id, scope)", "users_role (id, scope)", "RESTRICT"),
    (
        "users_user_role",
        "ur_user_organization_fk",
        "(user_id, organization_id)",
        "users_user (id, organization_id)",
        "CASCADE",
    ),
)


class Migration(migrations.Migration):
    dependencies = [("users", "0003_rbac")]

    operations = [
        migrations.RunSQL(
            sql=f"ALTER TABLE {table} ADD CONSTRAINT {name} FOREIGN KEY {columns} REFERENCES {target} "
            f"ON DELETE {on_delete}",
            reverse_sql=f"ALTER TABLE {table} DROP CONSTRAINT {name}",
        )
        for table, name, columns, target, on_delete in FOREIGN_KEYS
    ]
