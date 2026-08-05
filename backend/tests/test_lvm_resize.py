"""Изменение размера пула LVM трогает устройства — значит, на хосте."""
import inspect

from app.api import host


def test_every_device_command_runs_in_the_host_namespace():
    """Симптом с живого сервера:

        /dev/mapper/control: open failed: Operation not permitted
        Cannot use /dev/loop0 (lost): device not found

    /dev контейнера — это не /dev хоста: ни device-mapper, ни loop-устройств
    там нет. Чтение размеров пула (vgs) через nsenter уже шло, а изменение
    размера запускало pvresize/losetup/truncate прямо в контейнере."""
    src = inspect.getsource(host.resize_lvm_storage)
    for tool in ("pvresize", "losetup", "truncate"):
        assert tool in src, f"{tool} пропал из функции — тест устарел"
    # Ни одна команда не должна вызываться в обход host_run
    assert "subprocess.run(" not in src, (
        "команда изменения размера выполняется в контейнере, а не на хосте")
    assert src.count("host_run(") >= 5


def test_host_run_enters_the_host_mount_namespace():
    src = inspect.getsource(host.host_run)
    assert "nsenter" in src and "/proc/1/ns/mnt" in src


def test_host_run_prefixes_the_command_it_is_given():
    """Проверяем именно состав аргументов, а не факт вызова."""
    captured = {}

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return None

    original = host.subprocess.run
    host.subprocess.run = fake_run
    try:
        host.host_run(["pvresize", "/dev/loop0"], check=True)
    finally:
        host.subprocess.run = original

    assert captured["cmd"] == ["nsenter", "--mount=/proc/1/ns/mnt", "pvresize", "/dev/loop0"]
    assert captured["kwargs"]["check"] is True
    assert captured["kwargs"]["capture_output"] is True


def test_lvm_refusal_is_reported_as_a_client_error_not_a_500():
    """500 маскируется кодом обращения, и настоящий ответ LVM пропадает —
    именно из-за этого причина «Operation not permitted» так долго не была
    видна."""
    src = inspect.getsource(host.resize_lvm_storage)
    assert "status_code=400" in src, "отказ LVM должен быть 400, а не 500"
    assert "Ответ LVM" in src, "текст от LVM должен доходить до пользователя"
    # Общий except не должен заворачивать осмысленные 4xx обратно в 500
    assert "except HTTPException:" in src
