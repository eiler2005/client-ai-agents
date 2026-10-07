# Коммерческие предложения

Здесь лежат КП по реальным клиентам. **Каталог не коммитится**: правило в `.gitignore`
пропускает только этот файл и `.gitkeep`. Цены и условия не попадают в историю
репозитория.

```sh
uv run assess new db-01-support-kp --kind proposal
uv run assess check                    # форма файла и ссылки в профиль компании
uv run assess build                    # фигуры и страницы в docs/
uv run assess proposal --only db-01-support-kp
```

Раздел «О компании» в КП не пишется руками — он собирается из
[../src/content/company.yaml](../src/content/company.yaml), где у каждой цифры есть
источник и дата. Услуги (`offerings`), факты и кейсы указываются идентификаторами из
этого профиля; придумать в предложении кейс, которого нет в профиле, проверка не даст.

Если КП идёт после обследования, укажите `project.assessment` — в раздел «Понимание
задачи» подтянутся решение, пробелы и опора из оценки.

Образец заполнения — [../examples/proposals/](../examples/proposals/); собрать его целиком:

```sh
uv run assess --demo build
uv run assess --demo proposal --out dist/kp-demo
```

Как писать КП и что проверить перед отправкой — [../docs/PROPOSAL.md](../docs/PROPOSAL.md).
