"""Marqueur des comptes de démonstration (§26, seed_demo). Migration additive : aucune donnée modifiée.

La colonne reçoit aussi une valeur par défaut en base (false) pour les insertions hors ORM ; l'ORM fournit
toujours la valeur, sans INSERT … RETURNING (voir le commentaire du modèle).
"""

from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [
        ("users", "0005_user_security_stamp"),
    ]

    operations = [
        migrations.AddField(
            model_name="user",
            name="is_demo",
            field=models.BooleanField(default=False, verbose_name="compte de démonstration"),
        ),
        migrations.RunSQL(
            sql="ALTER TABLE users_user ALTER COLUMN is_demo SET DEFAULT false;",
            reverse_sql="ALTER TABLE users_user ALTER COLUMN is_demo DROP DEFAULT;",
        ),
    ]
