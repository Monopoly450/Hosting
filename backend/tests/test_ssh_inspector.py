from app.services.ssh_inspector import SSHInspector


def test_uses_bastion_true_when_host_and_user_set():
    insp = SSHInspector(
        host="10.0.0.5", username="root", password="p",
        bastion_host="bastion.example.com", bastion_username="jump", bastion_password="bp",
    )
    assert insp.uses_bastion is True


def test_uses_bastion_false_without_bastion():
    insp = SSHInspector(host="10.0.0.5", username="root", password="p")
    assert insp.uses_bastion is False


def test_uses_bastion_false_with_partial_bastion():
    # Хост есть, но пользователь не задан — бастион не активируется
    insp = SSHInspector(
        host="10.0.0.5", username="root", password="p",
        bastion_host="bastion.example.com",
    )
    assert insp.uses_bastion is False


def test_bastion_port_defaults_to_22():
    insp = SSHInspector(host="h", username="u", password="p", bastion_host="b",
                        bastion_username="bu", bastion_password="bp", bastion_port=None)
    assert insp.bastion_port == 22


def test_close_clients_handles_none():
    # Не должно бросать исключение, даже если клиенты None
    SSHInspector.close_clients(None, None)
