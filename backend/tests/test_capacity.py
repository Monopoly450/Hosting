"""Вместимость хоста: диск нельзя обещать дважды."""
from app.core.capacity import available_disk_gb


def test_thin_disks_do_not_look_free_after_they_are_promised():
    """Сценарий с живого сервера: на хосте 200 ГБ, свободно 180 ГБ, но 3 ВМ
    по 50 ГБ уже созданы и пока почти ничего не записали. Наивная проверка по
    свободному месту разрешит создать ещё одну на 50 ГБ — и та навсегда
    зависнет в планировании, когда место понадобится по-настоящему."""
    assert available_disk_gb(200.0, 180.0, reserved_gb=150.0) == 50.0
    # четвёртая такая ВМ уже не помещается
    assert available_disk_gb(200.0, 180.0, reserved_gb=200.0) == 0.0


def test_ten_vms_at_once_cannot_all_fit():
    """Именно этот случай пользователь и поймал: 10 ВМ по 50 ГБ на сервере,
    где столько места нет. Проверка должна начать отказывать по мере роста
    зарезервированного, а не пропускать все десять."""
    host_total, host_free = 200.0, 190.0
    reserved = 0.0
    accepted = 0
    for _ in range(10):
        if 50.0 <= available_disk_gb(host_total, host_free, reserved):
            accepted += 1
            reserved += 50.0
    assert accepted == 4, "должны пройти только те, что реально помещаются"


def test_free_space_still_wins_when_disk_is_full_of_non_vm_data():
    """Обратный случай: ВМ обещано немного, но диск забит образами и
    бэкапами. Тогда ограничивать должно фактическое свободное место."""
    assert available_disk_gb(200.0, 5.0, reserved_gb=20.0) == 5.0


def test_estimates_converge_when_vms_have_filled_their_disks():
    """Когда ВМ заполнили обещанное, обе оценки совпадают — проверка не
    становится вдвое строже сама по себе."""
    assert available_disk_gb(200.0, 50.0, reserved_gb=150.0) == 50.0


def test_never_negative():
    assert available_disk_gb(100.0, 0.0, reserved_gb=500.0) == 0.0
