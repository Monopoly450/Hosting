#!/usr/bin/env bash

# Скрипт для исправления настроек KubeVirt и CDI после перезагрузки
set -e

echo "[INFO] 1. Настройка StorageProfile 'local-path'..."
kubectl patch storageprofile local-path \
  --type=merge \
  -p '{"spec": {"claimPropertySets": [{"accessModes": ["ReadWriteOnce"], "volumeMode": "Filesystem"}]}}'

echo "[INFO] 2. Настройка Scratch Space Storage Class для CDI..."
kubectl patch cdi cdi \
  --type=merge \
  --patch '{"spec": {"config": {"scratchSpaceStorageClass": "local-path"}}}'

# Проверка KVM на хосте
if [ ! -e /dev/kvm ]; then
    echo "[INFO] 3. Устройство /dev/kvm не найдено! Настраиваем KubeVirt в режим программной эмуляции..."
    kubectl patch kubevirt kubevirt -n kubevirt \
      --type merge \
      -p '{"spec":{"configuration":{"developerConfiguration":{"useEmulation":true}}}}'
else
    echo "[INFO] 3. Аппаратная виртуализация KVM доступна на хосте, эмуляция не требуется."
fi

echo "[INFO] Проверяем статус эмуляции в KubeVirt..."
kubectl get kubevirt kubevirt -n kubevirt -o jsonpath='{.spec.configuration.developerConfiguration.useEmulation}'
echo ""

echo "[INFO] Удаляем зависший под виртуалки, чтобы применились новые настройки..."
kubectl delete pod -l kubevirt.io/domain=hi || true

echo "[INFO] Все исправления применены! Виртуалка должна перезапуститься автоматически."
