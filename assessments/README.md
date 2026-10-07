# Оценки проектов

Здесь лежат файлы оценок по реальным проектам. **Каталог не коммитится**: правило в
`.gitignore` пропускает только этот файл и `.gitkeep`. Данные заказчика не попадают в
историю репозитория — ни при `git add .`, ни случайно.

Как работать:

```sh
uv run assess new banк-01-support     # создать файл из templates/assessment.yaml
uv run assess check                   # проверять по ходу заполнения
uv run assess score                   # посмотреть балл, не собирая отчёт
uv run assess build                   # фигуры и страницы в docs/
uv run assess pdf --only banк-01-support
```

Пока статус `draft`, незаполненные измерения — норма. Полные проверки включаются на
`status: final`: у каждого измерения должны быть уверенность, источник и рекомендация
при уровне 2 и ниже, у действий — владельцы, у рисков — меры.

Образцы заполнения лежат в [../examples/](../examples/) — это вымышленные проекты,
их можно собирать и печатать как есть:

```sh
uv run assess --input examples build
uv run assess --input examples pdf --out dist/pdf-demo
```
