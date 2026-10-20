"""The shop people, the order of Ben and the start of the chat of Ann and Ben. Their ids are those of the docs (34, 42, 43): calls and
the directory take integer ids."""

from django.conf import settings
from django.db import migrations

PEOPLE = [(34, "ann", "Ann", "Support", True), (42, "ben", "Ben", "Customer", False), (43, "cara", "Cara", "Warehouse", True)]


def create(apps, schema_editor):
    User = apps.get_model(*settings.AUTH_USER_MODEL.split("."))
    Profile, Order, Message = apps.get_model("store", "Profile"), apps.get_model("store", "Order"), apps.get_model("store", "Message")

    for pk, username, name, role, staff in PEOPLE:
        user = User.objects.create(pk=pk, username=username, first_name=name, is_staff=staff, password="!")
        Profile.objects.create(user=user, role=role, avatar=f"/static/avatars/{username}.svg")

    Order.objects.create(pk=1042, customer_id=42, item="Two ceramic mugs", status="placed")
    Message.objects.create(sender_id=42, text="Hi! Has my order left yet?")
    Message.objects.create(sender_id=34, text="Hi Ben, it is being packed now. I will let you know.")


class Migration(migrations.Migration):
    dependencies = [("store", "0001_initial"), migrations.swappable_dependency(settings.AUTH_USER_MODEL)]
    operations = [migrations.RunPython(create, migrations.RunPython.noop)]
