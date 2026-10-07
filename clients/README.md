# Локальные проекты клиентов

Общая база проекта публикуется в GitHub. Материалы реальных клиентов хранятся
отдельно, в `clients/<client-id>/`, и остаются на рабочей машине. В Git из этого
каталога входят только этот README и `.gitkeep`.

Рекомендуемая структура одного проекта:

```text
clients/<client-id>/
  01-discovery/       # запрос, материалы встречи, согласованные вводные
  02-presentation/    # JSON/YAML презентации, изображения и схемы
  03-specification/   # ТЗ и рабочие документы
  assessments/       # оценки проекта
  proposals/         # коммерческие предложения
  handoff/           # состояние сессии и результаты проверки
dist/clients/<client-id>/  # собранные документы, превью и манифесты, вне Git
```

CLI поддерживает отдельные каталоги оценок и предложений. Вместо `client-id`
укажите локальный идентификатор проекта:

```sh
uv run assess --input clients/client-id/assessments \
  --proposals clients/client-id/proposals new project-id
uv run assess --input clients/client-id/assessments \
  --proposals clients/client-id/proposals check
uv run assess --input clients/client-id/assessments \
  --proposals clients/client-id/proposals \
  --docs dist/clients/client-id/docs build
```

Источники презентации передаются сборщику через `--spec`; команды описаны в
[стандарте презентаций](../docs/PRESENTATION.md). Для выхода используйте отдельный
каталог в `dist/clients/`. Ранее собранные локальные файлы в `dist/` также не публикуются.

Старый путь `docs/client-projects/` исключён из Git. `.githooks/privacy-check`
останавливает принудительное добавление клиентских файлов, а `pre-push` проверяет
все отправляемые коммиты: удаление файла поздним коммитом не очищает историю.
Ветки `local/` предназначены только для локальной истории.

Эти папки не синхронизируются через общий GitHub-репозиторий. Резервное копирование
и доступ к материалам согласуются отдельно. В `examples/` допустимы только
полностью вымышленные проекты, созданные с нуля.
