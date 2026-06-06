#!/usr/bin/env bash

# Скрипт для исправления настроек KubeVirt CDI
set -e

echo "[INFO] 1. Настройка StorageProfile 'local-path'..."
kubectl patch storageprofile local-path \
  --type=merge \
  -p '{"spec": {"claimPropertySets": [{"accessModes": ["ReadWriteOnce"], "volumeMode": "Filesystem"}]}}'

echo "[INFO] 2. Настройка Scratch Space Storage Class для CDI..."
kubectl patch cdi cdi \
  --type=merge \
  --patch '{"spec": {"config": {"scratchSpaceStorageClass": "local-path"}}}'

echo "[INFO] Проверяем статус CDI конфигурации..."
kubectl get cdi cdi -o yaml | grep scratchSpaceStorageClass -B 2 -A 2 || echo "Scratch SC configuration not found in spec"

echo "[INFO] Успешно применено! Удаляем зависший импорт, чтобы он перезапустился с новыми параметрами..."
kubectl delete pvc mama-disk-scratch || true
kubectl delete dv mama-disk || true

echo "[INFO] Готово! Пересоздайте ВМ 'mama' на панели, и импорт пойдет."
