terraform {
  required_providers {
    aegis = {
      source = "byteburners/aegis"
    }
  }
}

# Адрес и токен можно задать здесь или через переменные окружения
# AEGIS_URL и AEGIS_TOKEN (токен создаётся во вкладке «API-токены» панели).
provider "aegis" {
  url   = "http://SERVER:8000"
  token = var.aegis_token
}

variable "aegis_token" {
  type      = string
  sensitive = true
}

# Виртуальная машина
resource "aegis_vm" "web" {
  name      = "web-1"
  os_type   = "ubuntu"
  cpu_cores = 2
  memory_gb = 2
  disk_gb   = 20
}

# Управляемая база данных
resource "aegis_database" "app" {
  name   = "app_db"
  engine = "postgresql"
}

# Чтение существующей ВМ
data "aegis_vm" "existing" {
  name = "some-existing-vm"
}

output "web_ip" {
  value = aegis_vm.web.ip_address
}

output "web_ssh_port" {
  value = aegis_vm.web.ssh_port
}

output "db_connection" {
  value = {
    host     = aegis_database.app.db_host
    user     = aegis_database.app.db_user
    password = aegis_database.app.db_password
  }
  sensitive = true
}
