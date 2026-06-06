#!/usr/bin/env bash

# Скрипт для настройки StorageProfile local-path по умолчанию в KubeVirt CDI
set -e

echo "[INFO] Настройка StorageProfile 'local-path'..."
kubectl patch storageprofile local-path \
  --type=merge \
  -p '{"spec": {"claimPropertySets": [{"accessModes": ["ReadWriteOnce"], "volumeMode": "Filesystem"}]}}'

echo "[INFO] Успешно применено! Проверяем статус StorageProfile..."
kubectl describe storageprofile local-path

echo "[INFO] Проверяем статус DataVolume hhh-disk..."
kubectl get dv hhh-disk
