# Terraform-провайдер для ByteBurners (Aegis)

Управляйте инфраструктурой панели хостинга ByteBurners как кодом: виртуальные
машины и базы данных описываются в `.tf`-файлах, а `terraform apply` приводит
панель в нужное состояние.

Аутентификация выполняется персональным **API-токеном** (`aeg_...`), который
создаётся во вкладке **«API-токены»** панели (или командой `aegis token create`).

## Возможности

| Тип | Имя | Описание |
|-----|-----|----------|
| resource | `aegis_vm` | Виртуальная машина (KubeVirt) |
| resource | `aegis_database` | Управляемая БД PostgreSQL / MySQL |
| data source | `aegis_vm` | Чтение данных существующей ВМ |

## Установка (локальная сборка)

Публичный реестр пока не используется, поэтому провайдер ставится локально.

```bash
cd terraform-provider-aegis
make install            # соберёт и положит в ~/.terraform.d/plugins/...
```

Либо через `dev_overrides` в `~/.terraformrc` (без установки в каталог плагинов):

```hcl
provider_installation {
  dev_overrides {
    "byteburners/aegis" = "/абсолютный/путь/к/terraform-provider-aegis"
  }
  direct {}
}
```

Затем `go build -o terraform-provider-aegis .` в каталоге провайдера.

## Настройка провайдера

```hcl
terraform {
  required_providers {
    aegis = {
      source = "byteburners/aegis"
    }
  }
}

provider "aegis" {
  url   = "http://SERVER:8000"   # или переменная окружения AEGIS_URL
  token = var.aegis_token        # или переменная окружения AEGIS_TOKEN
}
```

| Аргумент | Обязателен | Env | Описание |
|----------|-----------|-----|----------|
| `url` | да | `AEGIS_URL` | Адрес панели |
| `token` | да | `AEGIS_TOKEN` | Персональный API-токен `aeg_...` |

## Пример

```hcl
resource "aegis_vm" "web" {
  name      = "web-1"
  os_type   = "ubuntu"
  cpu_cores = 2
  memory_gb = 2
  disk_gb   = 20
}

resource "aegis_database" "app" {
  name   = "app_db"
  engine = "postgresql"
}

output "web_ip" {
  value = aegis_vm.web.ip_address
}
```

Полный пример — в [`examples/main.tf`](examples/main.tf).

## Ресурс `aegis_vm`

**Аргументы**

| Поле | Тип | Обяз. | Примечание |
|------|-----|-------|-----------|
| `name` | string | да | Имя ВМ (пересоздаёт при изменении) |
| `os_type` | string | да | `ubuntu`, `debian`, `windows`, `proxmox`, `truenas`, `custom` … |
| `cpu_cores` | number | да | 1–16 |
| `memory_gb` | number | да | 1–64 |
| `disk_gb` | number | да | 10–500 |
| `custom_image` | string | нет | Имя файла образа при `os_type = custom` |
| `wait_for_ip` | bool | нет | Ждать выдачи IP (по умолчанию `true`). Для ISO-ОС (Windows/Proxmox/TrueNAS) поставьте `false` — им нужна ручная установка |

**Вычисляемые поля:** `id`, `task_id`, `status`, `ip_address`, `ssh_port`.

> Изменение любого параметра создания пересоздаёт ВМ (`RequiresReplace`).

**Импорт** по имени:

```bash
terraform import aegis_vm.web web-1
```

## Ресурс `aegis_database`

**Аргументы:** `name` (обяз.), `engine` (`postgresql` по умолчанию, либо `mysql`).

**Вычисляемые поля:** `id`, `db_user`, `db_password` (sensitive), `db_host`, `status`.

**Импорт** по числовому id:

```bash
terraform import aegis_database.app 5
```

## Разработка

```bash
make build   # сборка бинарника
make test    # unit-тесты клиента (mock-сервер)
make vet     # go vet
```

Провайдер написан на [terraform-plugin-framework](https://github.com/hashicorp/terraform-plugin-framework).
Структура:

```
main.go                          точка входа (providerserver.Serve)
internal/client/                 HTTP-клиент к REST API панели
internal/provider/               провайдер, ресурсы и data source
examples/                        пример конфигурации
```
