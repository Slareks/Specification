#!/bin/bash
set -e

echo "===> Запуск Ansible playbook"
ansible-playbook -i inventory/hosts.ini site.yml

echo "===> Запускаем основной процесс: $@"
exec "$@"
