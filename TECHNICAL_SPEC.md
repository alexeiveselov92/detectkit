# detectkit - Техническая спецификация

> **ВАЖНО**: Этот документ создан на основе init_plan.md без упрощений.
> Все детали из оригинального плана должны быть сохранены.

## 1. Общее описание

**Название:** detectkit
**Язык:** Python
**Назначение:** Библиотека для аналитиков и дата-инженеров для мониторинга метрик с автоматическим обнаружением аномалий

**Основной принцип:** Работа через numpy-массивы (без pandas в ядре логики)

---

## 2. Архитектура данных

### 2.1. Входные данные от аналитика

Аналитик предоставляет SQL-запрос к БД который возвращает:
- **Временная колонка** - интервалы времени (10 мин, час и т.д. - настраиваемо)
- **Колонка метрики** - значения метрики
- **Сезонные колонки** (опционально) - дополнительные колонки для учета сезонности

Аналитик указывает маппинг колонок (где время, где метрика, где сезонные данные).

### 2.2. Внутренние таблицы

**ВАЖНО:** У нас будут менеджеры баз данных с универсальными методами работы с разными таблицами. Для работы менеджеров с внутренними таблицами у нас отдельно должны быть модели или датаклассы таблиц.

**ВАЖНО:** Для разных БД мы можем хранить таблицы в разных схемах или database (как в ClickHouse). Управляем этим из profiles:
- PostgreSQL/MySQL: schema внутри database
- ClickHouse: database = schema (нет вложенности)

Пример: таблицы в ClickHouse хранятся в `marts` → доступны как `marts._dtk_...`

**Общие таблицы по умолчанию**, но гибко настраиваемые:
- Для разных метрик можно использовать разные таблицы
- Можно группировать метрики по разным таблицам
- Даже если каждая метрика в своей таблице - мы передаем metric_name в таблицу (т.к. используем универсальные методы)

#### Таблица 1: `_dtk_datapoints`

Сохраненные исторические данные метрик.

**ClickHouse DDL:**
```sql
CREATE TABLE _dtk_datapoints (
    metric_name String,
    timestamp DateTime64(3, 'UTC'),
    value Nullable(Float64),
    seasonality_data String,              -- JSON: {"day_of_week": 1, "hour": 10, ...}
    interval_seconds Int32,               -- интервал в секундах (600 для 10min, 3600 для 1h)
    seasonality_columns String,           -- JSON массив: ["day_of_week", "hour", "is_holiday"]
    created_at DateTime64(3, 'UTC'),
    PRIMARY KEY (metric_name, timestamp)
)
ENGINE = MergeTree()
ORDER BY (metric_name, timestamp)
```

**Поля:**
- `metric_name` - идентификатор метрики
- `timestamp` - временная метка (UTC обязательно)
- `value` - значение метрики (Nullable для пропущенных данных)
- `seasonality_data` - JSON с сезонными данными для этой точки
- `interval_seconds` - интервал метрики в секундах
- `seasonality_columns` - JSON массив названий сезонных колонок (для валидации структуры)
- `created_at` - время записи в таблицу

#### Таблица 2: `_dtk_detections`

Результаты работы детекторов.

**ClickHouse DDL:**
```sql
CREATE TABLE _dtk_detections (
    metric_name String,
    detector_id String,                   -- хэш детектора
    timestamp DateTime64(3, 'UTC'),
    is_anomaly Bool,
    confidence_lower Nullable(Float64),
    confidence_upper Nullable(Float64),
    value Nullable(Float64),              -- значение метрики
    detector_params String,               -- JSON (отсортированные параметры)
    detection_metadata String,            -- JSON (missing_ratio, severity, direction и т.д.)
    created_at DateTime64(3, 'UTC'),
    PRIMARY KEY (metric_name, detector_id, timestamp)
)
ENGINE = MergeTree()
ORDER BY (metric_name, detector_id, timestamp)
```

**Уникальный ключ детектора (detector_id):** хэш из названия детектора + отсортированных не-дефолтных параметров

**Поля:**
- `metric_name` - идентификатор метрики
- `detector_id` - хэш детектора (class name + non-default params)
- `timestamp` - временная метка (UTC)
- `is_anomaly` - флаг аномалии (Bool)
- `confidence_lower/upper` - границы доверительного интервала
- `value` - значение метрики
- `detector_params` - JSON отсортированных параметров детектора
- `detection_metadata` - JSON метаданных (missing_ratio, insufficient_seasonality_data и т.д.)
- `created_at` - время записи

#### Таблица 3: `_dtk_tasks`

Таблица блокировок и статусов задач для предотвращения параллельных запусков.

**ClickHouse DDL:**
```sql
CREATE TABLE _dtk_tasks (
    metric_name String,
    detector_id String,                    -- пустая строка "" для load процесса
    process_type String,                   -- 'load' / 'detect' / 'alert'
    status String,                         -- 'running' / 'completed' / 'failed'
    started_at DateTime64(3, 'UTC'),
    updated_at DateTime64(3, 'UTC'),
    last_processed_timestamp Nullable(DateTime64(3, 'UTC')),
    error_message Nullable(String),
    timeout_seconds Int32,
    PRIMARY KEY (metric_name, detector_id, process_type)
)
ENGINE = ReplacingMergeTree(updated_at)
ORDER BY (metric_name, detector_id, process_type)
```

**ВАЖНО:** `last_processed_timestamp` используется только для информационных целей. В логике работы библиотеки мы на него НЕ полагаемся для определения следующего батча (слишком велика вероятность дублирования). Для определения начальной точки используем `get_last_timestamp()` из `_dtk_datapoints` или `_dtk_detections`.

### 2.3. Хранение сезонных колонок

**Проблема:** Разные метрики имеют разные сезонные колонки, но нужно типизированное хранилище.

**Решение:** Хранение в виде JSON и быстрый парсинг при извлечении.

**Обоснование:**
- Универсальность (не нужно создавать схемы под каждую метрику)
- Для 100 метрик с 6 месяцами данных ~150 MB JSON (приемлемо)
- Используем `orjson` для быстрого парсинга (в 4-5 раз быстрее стандартного json)

### 2.4. Настройка таблиц

**В конфиге проекта (`detectkit_project.yml`):**
```yaml
tables:
  default:
    datapoints: "_dtk_datapoints"
    detections: "_dtk_detections"
    tasks: "_dtk_tasks"
```

**Переопределение в конфиге метрики:**
```yaml
metric:
  name: "orders_count_10min"
  tables:
    datapoints: "_dtk_datapoints_sales"  # опционально
    detections: "_dtk_detections_sales"  # опционально
    # tasks не переопределяется - общая для всех
```

---

## 3. Базовая архитектура менеджера БД

**КРИТИЧЕСКИ ВАЖНО:** Менеджер БД должен быть УНИВЕРСАЛЬНЫМ с методами общего назначения, а НЕ специфичными для внутренних таблиц.

### 3.1. BaseDatabaseManager - Универсальный интерфейс

```python
from abc import ABC, abstractmethod
from typing import Dict, List, Optional, Any
import numpy as np
from datetime import datetime

class BaseDatabaseManager(ABC):
    """
    Универсальный менеджер БД для работы с detectkit.

    НЕ хардкодит работу с внутренними таблицами - использует универсальные методы.
    Специфичная логика для _dtk_* таблиц должна быть в отдельном слое поверх этого класса.
    """

    @abstractmethod
    def execute_query(self, query: str, params: Optional[Dict[str, Any]] = None) -> List[Dict]:
        """
        Выполнить SQL запрос и вернуть результат как список словарей.

        Args:
            query: SQL запрос (может содержать Jinja2 шаблоны)
            params: Параметры для Jinja2 рендеринга и SQL биндинга

        Returns:
            Список словарей (строк результата)
        """
        pass

    @abstractmethod
    def execute_query_numpy(self, query: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, np.ndarray]:
        """
        Выполнить запрос и вернуть результат как словарь numpy массивов.

        Args:
            query: SQL запрос
            params: Параметры

        Returns:
            Dict[column_name -> np.ndarray]
        """
        pass

    @abstractmethod
    def create_table(self, table_name: str, table_model: 'TableModel'):
        """
        Создать таблицу по модели.

        Args:
            table_name: Имя таблицы
            table_model: Модель таблицы (содержит схему колонок)
        """
        pass

    @abstractmethod
    def table_exists(self, table_name: str, schema: Optional[str] = None) -> bool:
        """
        Проверить существование таблицы.

        Args:
            table_name: Имя таблицы
            schema: Схема (для Postgres/MySQL) или database (для ClickHouse)

        Returns:
            True если таблица существует
        """
        pass

    @abstractmethod
    def insert_batch(
        self,
        table_name: str,
        data: Dict[str, np.ndarray],
        conflict_strategy: str = "ignore"
    ) -> int:
        """
        Вставить батч данных в таблицу.

        Args:
            table_name: Имя таблицы
            data: Словарь column_name -> np.ndarray
            conflict_strategy: "ignore" (INSERT IGNORE) или "update" (UPSERT)

        Returns:
            Количество вставленных строк
        """
        pass

    @abstractmethod
    def get_last_timestamp(
        self,
        table_name: str,
        metric_name: str,
        timestamp_column: str = "timestamp"
    ) -> Optional[datetime]:
        """
        Получить последнюю временную точку для метрики.

        Args:
            table_name: Имя таблицы
            metric_name: Имя метрики
            timestamp_column: Название колонки с timestamp

        Returns:
            Последний timestamp или None если данных нет
        """
        pass

    @abstractmethod
    def upsert_task_status(
        self,
        metric_name: str,
        detector_id: str,
        process_type: str,
        status: str,
        started_at: Optional[datetime] = None,
        updated_at: Optional[datetime] = None,
        last_processed_timestamp: Optional[datetime] = None,
        error_message: Optional[str] = None,
        timeout_seconds: int = 3600
    ):
        """
        Обновить или создать статус задачи в _dtk_tasks.

        Специфичный метод для работы с таблицей блокировок.

        Args:
            metric_name: Имя метрики
            detector_id: ID детектора (или "" для load)
            process_type: 'load' / 'detect' / 'alert'
            status: 'running' / 'completed' / 'failed'
            started_at: Время начала
            updated_at: Время обновления
            last_processed_timestamp: Последняя обработанная точка (информационно)
            error_message: Сообщение об ошибке
            timeout_seconds: Timeout для процесса

        Implementation notes:
            - ClickHouse: DELETE + INSERT
            - Postgres: INSERT ... ON CONFLICT UPDATE
        """
        pass

    @abstractmethod
    def get_task_status(
        self,
        metric_name: str,
        detector_id: str,
        process_type: str
    ) -> Optional[Dict]:
        """
        Получить статус задачи из _dtk_tasks.

        Returns:
            Словарь с полями задачи или None
        """
        pass

    @property
    @abstractmethod
    def internal_location(self) -> str:
        """
        Полный путь к internal схеме/database для _dtk_* таблиц.

        Returns:
            ClickHouse: "marts"
            Postgres: "analytics.dtk_meta"
        """
        pass

    @property
    @abstractmethod
    def data_location(self) -> str:
        """
        Полный путь к пользовательским данным (data schema/database).

        Returns:
            ClickHouse: "default"
            Postgres: "analytics.public"
        """
        pass

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()
```

### 3.2. TableModel - Модель таблицы

```python
from dataclasses import dataclass
from typing import List, Dict, Any

@dataclass
class ColumnDefinition:
    """Определение колонки таблицы."""
    name: str
    type: str          # "String", "Int32", "Float64", "DateTime64(3, 'UTC')", etc.
    nullable: bool = False
    default: Optional[Any] = None

@dataclass
class TableModel:
    """
    Модель таблицы для создания через BaseDatabaseManager.

    Используется для универсального создания таблиц в разных БД.
    """
    columns: List[ColumnDefinition]
    primary_key: List[str]
    engine: Optional[str] = None  # Для ClickHouse: "MergeTree()", "ReplacingMergeTree(updated_at)"
    order_by: Optional[List[str]] = None  # Для ClickHouse
```

**Пример использования:**
```python
# Модель для _dtk_datapoints
datapoints_model = TableModel(
    columns=[
        ColumnDefinition("metric_name", "String"),
        ColumnDefinition("timestamp", "DateTime64(3, 'UTC')"),
        ColumnDefinition("value", "Float64", nullable=True),
        ColumnDefinition("seasonality_data", "String"),
        ColumnDefinition("interval_seconds", "Int32"),
        ColumnDefinition("seasonality_columns", "String"),
        ColumnDefinition("created_at", "DateTime64(3, 'UTC')"),
    ],
    primary_key=["metric_name", "timestamp"],
    engine="MergeTree()",
    order_by=["metric_name", "timestamp"]
)

# Создание таблицы
db_manager.create_table("_dtk_datapoints", datapoints_model)
```

---

## 4. Profiles и схемы/databases

### 4.1. Унификация схем в profiles

**ClickHouse profile:**
```yaml
clickhouse_prod:
  type: clickhouse
  host: localhost
  port: 9000
  user: default
  password: xxx

  # Для ClickHouse: database используется как schema
  database: default              # где лежат данные пользователя
  internal_database: marts       # где создавать _dtk_* таблицы
```

**Postgres profile:**
```yaml
postgres_prod:
  type: postgres
  host: localhost
  port: 5432
  user: postgres
  password: xxx

  database: analytics            # основная БД
  schema: public                 # где данные пользователя
  internal_schema: dtk_meta      # где создавать _dtk_* таблицы
```

**MySQL profile:**
```yaml
mysql_prod:
  type: mysql
  host: localhost
  port: 3306
  user: root
  password: xxx

  database: analytics
  schema: public
  internal_schema: dtk_meta
```

### 4.2. Расположение profiles.yml

**Два уровня (как в dbt):**
1. **Глобальный:** `~/.detectkit/profiles.yml`
2. **Проектный:** `<project>/profiles.yml` (переопределяет глобальный)

**Приоритет:** Проектный > Глобальный

---

## 5. Процесс: Загрузка данных метрики

### 5.1. Основной процесс

Аналитик указывает в конфиге метрики:
- **loading_start_time** - с какого времени загружать данные (UTC)
- **loading_batch_size** - размер батча в точках

Запрос содержит переменные для извлечения любого периода.
Данные загружаются **батчами** и сохраняются в `_dtk_datapoints`.

### 5.2. Конфигурация

```yaml
metric:
  loading_start_time: "2024-01-01 00:00:00"  # UTC
  loading_batch_size: 1000                   # количество точек
```

### 5.3. Идемпотентность загрузки

**Алгоритм определения начальной точки:**

```python
# 1. Получить последнюю загруженную точку из _dtk_datapoints
last_ts = db_manager.get_last_timestamp(
    table_name="_dtk_datapoints",
    metric_name=metric_name
)

# 2. Определить начало загрузки
if last_ts is None:
    start = loading_start_time  # первая загрузка
else:
    start = last_ts + interval  # продолжение с последней точки

# 3. Загрузить батч
end = start + (batch_size * interval)
batch_data = load_batch_from_source(start, end)

# 4. Записать в БД с конфликт-стратегией
db_manager.insert_batch(
    table_name="_dtk_datapoints",
    data=batch_data,
    conflict_strategy="ignore"  # INSERT IGNORE или ON CONFLICT DO NOTHING
)
```

**PRIMARY KEY (metric_name, timestamp) предотвращает дубли.**

При перезапуске продолжаем с последней записанной точки.

### 5.4. Валидация дубликатов

**КРИТИЧЕСКИ ВАЖНО:** Проверяем дубликаты в исходных данных (батче из source query):

```python
def validate_no_duplicates(timestamps: np.ndarray):
    """Проверка дубликатов через numpy."""
    unique_count = len(np.unique(timestamps))
    total_count = len(timestamps)

    if unique_count != total_count:
        raise ValueError(
            f"Duplicate timestamps in source data: "
            f"{total_count - unique_count} duplicates found"
        )
```

Это предотвращает проблемы на всех следующих этапах.

### 5.5. Обработка пропущенных данных

Если во входных данных отсутствуют точки (например, есть 12:10, 12:30, но нет 12:20):
- Генерируем полный временной ряд с NaN для пропущенных точек
- Сохраняем NaN в `_dtk_datapoints`
- **Требование:** все детекторы должны корректно работать с NaN

**Алгоритм заполнения:**
```python
def fill_missing_points(
    data: Dict[str, np.ndarray],
    interval_seconds: int,
    start: datetime,
    end: datetime
) -> Dict[str, np.ndarray]:
    """
    Генерация полного временного ряда.

    Если точки отсутствуют - заполняем NaN.
    """
    # Создаем полный диапазон временных точек
    expected_timestamps = pd.date_range(start, end, freq=f"{interval_seconds}s")

    # Находим пропущенные точки
    # Заполняем value и seasonality_data значениями NaN/None
    ...
```

### 5.6. SQL запросы с Jinja2

**Обязательные переменные в запросе:**
- `{{dtk_start_time}}` - начало периода
- `{{dtk_end_time}}` - конец периода

**Пример:**
```sql
SELECT
  toStartOfTenMinutes(created_at) as time_interval,
  count(*) as metric_value,
  toDayOfWeek(time_interval) as day_of_week,
  toHour(time_interval) as hour
FROM orders
WHERE created_at >= {{dtk_start_time}}
  AND created_at < {{dtk_end_time}}
GROUP BY time_interval, day_of_week, hour
ORDER BY time_interval
```

**ВАЖНО:** Время в БД ОБЯЗАТЕЛЬНО в UTC. Аналитики обязаны писать запрос возвращающий UTC время.

### 5.7. Ссылки на SQL файлы

**Структура проекта:**
```
project_root/
  ├── detectkit_project.yml
  ├── sql/                     # дефолтная папка (настраиваемо)
  │   ├── orders_query.sql
  │   └── analytics/
  │       └── user_metrics.sql
  └── metrics/
      └── orders_config.yml
```

**В конфиге метрики:**

Вариант 1: Inline SQL
```yaml
metric:
  name: "orders_count"
  query: |
    SELECT ...
```

Вариант 2: Ссылка на файл
```yaml
metric:
  name: "orders_count"
  query_file: "orders_query.sql"  # относительно sql/
  # или
  query_file: "analytics/user_metrics.sql"
```

**query и query_file взаимоисключающие** - либо query, либо query_file.

### 5.8. Батчи для загрузки

**Процесс загрузки батчами:**

Сценарий:
- Интервал: 10 минут
- Батч: 1000 точек = ~7 дней данных
- Нужно загрузить с 2024-01-01 по 2024-03-01 (60 дней ≈ 8640 точек)
- Будет выполнено 9 запросов к БД

Процесс:
1. Загрузка батча 1: 2024-01-01 00:00 → 2024-01-08 06:40 (1000 точек)
2. Валидация дубликатов
3. Заполнение пропущенных точек
4. Сохранение в `_dtk_datapoints` (INSERT IGNORE)
5. Обновление `_dtk_tasks.last_processed_timestamp` = 2024-01-08 06:40 (информационно)
6. Загрузка батча 2: 2024-01-08 06:50 → ...
7. ...

**ВАЖНО:** Для определения следующего батча НЕ используем `last_processed_timestamp` из `_dtk_tasks`.
Используем `get_last_timestamp()` из `_dtk_datapoints` - более надежно, исключает дубликаты.

---

## 6. Процесс: Детекция аномалий

### 6.1. Детекторы - типы и extras

**Типы детекторов:**
1. Статистические (встроенные):
   - MAD (Median Absolute Deviation)
   - Mean/Std (Z-score)
   - IQR (Interquartile Range)
   - Manual Bounds (ручные границы)

2. Продвинутые (через extras):
   - Prophet (Facebook)
   - TimesFM (Google)

**Структура extras:**
```toml
[project.optional-dependencies]
# Базы данных
clickhouse = ["clickhouse-driver>=0.2.0"]
postgres = ["psycopg2-binary>=2.9.0"]
mysql = ["pymysql>=1.0.0"]
all-db = ["detectkit[clickhouse,postgres,mysql]"]

# Детекторы
prophet = ["prophet>=1.1.0"]
timesfm = ["timesfm>=0.1.0"]
advanced-detectors = ["detectkit[prophet,timesfm]"]

# Комбинации
all = ["detectkit[all-db,advanced-detectors]"]
```

**Установка:**
```bash
pip install detectkit[clickhouse,prophet,timesfm]
```

### 6.2. Конфигурация детектора

```yaml
detectors:
  - name: "statistical_mad"
    params:
      threshold: 3.0
      window_size: 4320              # в точках (30 дней * 144 точек/день для 10min)
      start_time: "2024-02-01 00:00:00"  # после накопления истории
      batch_size: 500
      min_samples: 100
      min_samples_per_group: 10
      weighting: null                # null, 'linear', 'exponential'
      seasonality_components:
        - "day_of_week"
        - ["league_day", "hour"]     # комбинация
```

### 6.3. Работа с сезонностью

**Конфигурация компонент:**
- Каждая сезонная колонка может быть отдельной компонентой
- Комбинации колонок как одна компонента
- Гибкие вариации

**Пример:**
```yaml
# В конфиге метрики указываем все сезонные колонки
query_columns:
  seasonality: ["day_of_week", "hour", "league_day", "is_holiday"]

# В конфиге детектора группируем их
detectors:
  - name: "statistical_mad"
    params:
      seasonality_components:
        - ["day_of_week", "hour"]    # Компонента 1: день недели + час
        - "is_holiday"                # Компонента 2: праздник
        - "month"                     # Компонента 3: месяц
```

**Парсинг JSON сезонности:**

У нас должен быть один эффективный парсер сезонных колонок (т.к. они в JSON хранятся).

**Требования:**
- Используем `orjson` (в 4-5 раз быстрее стандартного json)
- Pre-allocation numpy массивов:
  1. Парсим первую JSON строку чтобы узнать ключи
  2. Создаем numpy массивы нужного размера (количество строк в батче)
  3. Заполняем по индексу вместо append
- Минимум копирований

```python
import orjson

def parse_seasonality_batch(json_strings: List[str]) -> Dict[str, np.ndarray]:
    """
    Максимально эффективный парсинг JSON → numpy массивы.

    Args:
        json_strings: Список JSON строк из БД

    Returns:
        Dict[column_name -> np.ndarray]
    """
    if not json_strings:
        return {}

    # Парсим первую строку чтобы узнать ключи
    first = orjson.loads(json_strings[0])
    keys = list(first.keys())
    n = len(json_strings)

    # Pre-allocate массивы
    arrays = {key: np.empty(n, dtype=np.float64) for key in keys}

    # Заполняем по индексу (без append)
    for i, json_str in enumerate(json_strings):
        if json_str is None or json_str == "":
            # Пропущенные данные - NaN везде
            for key in keys:
                arrays[key][i] = np.nan
        else:
            data = orjson.loads(json_str)
            for key in keys:
                arrays[key][i] = data.get(key, np.nan)

    return arrays
```

### 6.4. Историческое окно и батчи

**Детекторы работают с периодами, а не с отдельными точками.**

**Причины:**
- Эффективность: не нужно для каждой точки загружать историческое окно отдельно
- Оптимизация: данные загружаются массивами, расчет через смещение
- Универсальность: прод-режим (одна последняя точка) - частный случай периода

**Процесс:**
- Детектор настраивает `batch_size` (сколько точек детектировать за раз)
- Если период детекции: 1-10 марта, окно: 30 дней → загружается с 1 февраля по 10 марта
- Детектор получает ВЕСЬ массив и сам управляет смещением окна

**ВАЖНО:** Детектор должен получить весь массив данных и сам управлять смещением окна. Мы передаем `start_idx` - индекс с которого надо начать детектить.

**Окна и пропущенные точки:**

Сценарий:
- Интервал: 1 день
- Window: 10 точек (10 дней)
- Детектируем точку 2024-03-10
- Окно: [2024-02-29 ... 2024-03-09]
- В данных нет 2024-03-05 и 2024-03-07 (NaN)

**НЕ расширяем окно.** Окно всегда по календарным датам. Детектор сам решает как обрабатывать NaN.

### 6.5. Идемпотентность детекции

- Определяется последняя продетектированная точка из `_dtk_detections`
- При перезапуске процесс продолжается с последней обработанной точки
- Используем `get_last_timestamp(table="_dtk_detections", metric_name=..., detector_id=...)`

### 6.6. Хэш детектора

```python
def get_detector_hash(detector_class_name: str, params: Dict) -> str:
    """
    Генерация хэша детектора.

    Хэш = hash(class_name + sorted(non_default_params))
    """
    # Получаем параметры отличающиеся от дефолтных
    non_default = get_non_default_params(params, DEFAULT_PARAMS)

    # Сортируем
    sorted_params = sorted(non_default.items())

    # Генерируем хэш
    hash_input = f"{detector_class_name}:{sorted_params}"
    detector_id = hashlib.sha256(hash_input.encode()).hexdigest()[:16]

    return detector_id
```

**Пример:**
```yaml
detector:
  name: statistical_zscore
  params:
    threshold: 3.0
    window_days: 30
    min_samples: 100  # default = 100
```

Хэш = hash("statistical_zscore" + [("threshold", 3.0), ("window_days", 30)])

`min_samples` не включается, т.к. это дефолтное значение.

**При изменении параметра с дефолтного на другой:**
- Хэш меняется
- Создается новый детектор
- Старые результаты остаются в таблице (с другим хэшем)
- Начинается детекция заново с `start_time`

---

## 7. Базовый интерфейс детектора

**ВАЖНО:** Передача данных через датаклассы. НЕ создаем отдельные датаклассы для input/output/single point. Один датакласс для данных метрики, один для данных детекций.

**НЕ используем pandas даже для записи/чтения из БД!** Только numpy.

```python
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict
import numpy as np

@dataclass
class MetricData:
    """
    Данные метрики для детекции.

    Содержит весь массив данных (включая историческое окно).
    """
    metric_name: str
    timestamps: np.ndarray          # datetime64[ns]
    values: np.ndarray              # float64, может содержать NaN
    seasonality: Dict[str, np.ndarray]  # column_name -> np.ndarray
    interval_seconds: int

@dataclass
class DetectionData:
    """
    Результаты детекции.

    Содержит результаты для всех точек начиная с start_idx.
    """
    metric_name: str
    detector_id: str
    timestamps: np.ndarray          # datetime64[ns]
    is_anomaly: np.ndarray          # bool
    confidence_lower: np.ndarray    # float64
    confidence_upper: np.ndarray    # float64
    values: np.ndarray              # float64
    detector_params: Dict           # отсортированные не-дефолтные параметры
    detection_metadata: Dict[str, np.ndarray]  # missing_ratio, insufficient_seasonality_data, etc.

class BaseDetector(ABC):
    """Базовый интерфейс детектора."""

    DEFAULT_PARAMS = {}  # переопределяется в подклассах

    def __init__(self, **params):
        self.params = {**self.DEFAULT_PARAMS, **params}
        self._validate_params()

    @abstractmethod
    def _validate_params(self):
        """Валидация параметров детектора."""
        pass

    @abstractmethod
    def detect(self, data: MetricData, start_idx: int) -> DetectionData:
        """
        Основной метод детекции.

        Args:
            data: Полные данные метрики (включая историческое окно)
            start_idx: Индекс первой точки для детекции

        Returns:
            DetectionData для точек [start_idx:]
        """
        pass

    def get_id(self) -> str:
        """Генерация ID из класса + не-дефолтных параметров."""
        non_default = self._get_non_default_params()
        sorted_params = sorted(non_default.items())
        hash_input = f"{self.__class__.__name__}:{sorted_params}"
        return hashlib.sha256(hash_input.encode()).hexdigest()[:16]

    @abstractmethod
    def _get_non_default_params(self) -> Dict:
        """Возвращает параметры отличающиеся от дефолтных."""
        pass
```

---

## 8. Статистические детекторы - алгоритм

**Принцип:** Детектор работает с сезонностью через **мультипликативные корректировки** базовых статистик.

**Все операции через numpy - никакого pandas, минимум циклов, максимальная векторизация.**

### 8.1. Общий алгоритм

1. **Вычисляем веса для исторического окна** (опционально):
   - Экспоненциальные: более свежие точки важнее старых
   - Линейные: постепенное увеличение важности к текущей точке
   - Без весов: все точки равнозначны (веса = 1)
   - Веса нормализуются (сумма = 1)

2. **Вычисляем глобальные взвешенные статистики** для всего окна:
   - `global_center` (взвешенная медиана, среднее или другая мера центра)
   - `global_spread` (взвешенный MAD, std или другая мера разброса)

3. **Для каждой сезонной компоненты/группы**:
   - Создаем булевую маску через numpy по значениям компоненты/комбинации
   - Применяем маску к данным И весам
   - Вычисляем взвешенные `component_center` и `component_spread` для отфильтрованных данных
   - Получаем мультипликаторы:
     - `center_multiplier = component_center / global_center`
     - `spread_multiplier = component_spread / global_spread`

4. **Применяем корректировки**:
   - Перемножаем все мультипликаторы от всех компонент/групп
   - `adjusted_center = global_center × Π(center_multipliers)`
   - `adjusted_spread = global_spread × Π(spread_multipliers)`

5. **Строим доверительный интервал**:
   - `lower = adjusted_center - threshold × adjusted_spread`
   - `upper = adjusted_center + threshold × adjusted_spread`

### 8.2. Обработка edge cases

**Пустая маска (нет совпадений):**
- multiplier = 1.0 (нет корректировки)

**Маска < min_samples_per_group:**
- multiplier = 1.0 (игнорируем группу)
- Флаг в detection_metadata: `insufficient_seasonality_data = True`

**Пропущенные данные (NaN):**
- Детекторы игнорируют NaN (фильтруют из окна)
- В detection_metadata записываем `missing_ratio` = 1 - (valid_count / window_size)

### 8.3. Конфигурация групп сезонности

Примеры группировки:
```yaml
seasonality_components:
  - ["day_of_week", "hour"]    # Группа 1
  - "is_holiday"                # Группа 2
```

**Реализация фильтрации через numpy:**
```python
# Для текущей точки i
current_dow = seasonality['day_of_week'][i]
current_hour = seasonality['hour'][i]
current_holiday = seasonality['is_holiday'][i]

# Группа 1: день недели + час (комбинация)
mask1 = (
    (seasonality['day_of_week'][window_start:i] == current_dow) &
    (seasonality['hour'][window_start:i] == current_hour)
)

# Группа 2: is_holiday
mask2 = (seasonality['is_holiday'][window_start:i] == current_holiday)

# Фильтрация данных и весов
filtered_values_g1 = window_values[mask1]
filtered_weights_g1 = window_weights[mask1]

filtered_values_g2 = window_values[mask2]
filtered_weights_g2 = window_weights[mask2]

# Пересчитываем веса для отфильтрованных данных (нормализация)
filtered_weights_g1 = filtered_weights_g1 / filtered_weights_g1.sum()
filtered_weights_g2 = filtered_weights_g2 / filtered_weights_g2.sum()
```

### 8.4. Примеры детекторов

**MAD-детектор:**
- center = взвешенная медиана
- spread = взвешенный MAD

**Z-score детектор:**
- center = взвешенное среднее
- spread = взвешенный std

**IQR детектор:**
- center = взвешенная медиана
- spread = взвешенный IQR (Q3 - Q1)

**Manual Bounds:**
- Простая проверка: `value < lower_bound OR value > upper_bound`
- НЕТ сезонности, окна, весов

---

## 9. Алертинг

### 9.1. Архитектура

```
detectkit/
  ├── alerting/
  │   ├── channels/           # Каналы отправки
  │   │   ├── base.py        # Абстрактный channel
  │   │   ├── mattermost.py  # Приоритет
  │   │   ├── slack.py
  │   │   ├── telegram.py
  │   │   └── email.py
  │   ├── decision.py         # AlertDecisionEngine
  │   └── orchestrator.py     # AlertOrchestrator
```

### 9.2. AlertDecisionEngine

Логика принятия решения об отправке алерта:
- Проверяет наличие аномалии в последней точке
- Определяет направление аномалии (вверх/вниз)
- Проверяет соответствие настройкам (direction, consecutive_anomalies, min_detectors)
- Возвращает решение: отправлять алерт или нет

**Настройки:**
```yaml
alerting:
  conditions:
    min_detectors: 1                # минимум детекторов для алерта
    direction: "same"               # "same" / "any" / "up" / "down"
    consecutive_anomalies: 2        # опционально (по умолчанию = 1)
```

### 9.3. Определение направления аномалии

Из границ доверительного интервала:

```python
def get_direction(value: float, lower: float, upper: float) -> str:
    """
    Определение направления аномалии.

    Вычисляется через массивы а не построчно!
    """
    if value < lower:
        return "down"
    elif value > upper:
        return "up"
    else:
        return "none"
```

### 9.4. Логика consecutive_anomalies

**Конфиг:**
```yaml
conditions:
  direction: "same"
  consecutive_anomalies: 3
```

**Интерпретация:** "Алерт если 3 аномалии подряд в одном направлении"

**Сложный кейс:**
```
Point 1: anomaly, direction=down
Point 2: anomaly, direction=down
Point 3: anomaly, direction=up    # ← направление изменилось
Point 4: anomaly, direction=up
```

Тут только 2 аномалии в одном направлении - алерта не будет!

**Хранение состояния:** НЕ храним счетчик в БД. Всегда загружаем последние N точек и пересчитываем.

### 9.5. Несколько детекторов

**По умолчанию:** Если хотя бы 1 детектор нашел аномалию → алерт

**Параметр min_detectors:**
```yaml
conditions:
  min_detectors: 2  # нужно минимум 2 детектора
```

**Шаблоны:**

Если min_detectors == 1:
```yaml
template_single: |
  Anomaly detected in metric: {metric_name}
  Time: {timestamp} ({timezone})
  Value: {value}
  Confidence interval: [{confidence_lower}, {confidence_upper}]
  Detector: {detector_name}
```

Если min_detectors > 1:
```yaml
template_multiple: |
  Anomaly detected in metric: {metric_name}
  Time: {timestamp} ({timezone})
  Value: {value}
  Detectors triggered: {detectors_list}
```

### 9.6. AlertOrchestrator

**Координация процесса:**
1. Определяет последнюю полную временную точку относительно now (UTC):
   - Пример: сейчас 13:23, интервал 10 мин → точка 13:10
   - Формула: `floor(now, interval) - interval`

2. Загружает результаты всех детекторов для этой точки из `_dtk_detections`

3. Если данных нет → отправить no_data алерт (если `no_data_alert: true`)

4. Вызывает AlertDecisionEngine

5. При положительном решении → рендерит шаблон → отправляет через каналы

**ВАЖНО:** Последняя точка берется по UTC времени. В БД ОБЯЗАТЕЛЬНО UTC время.

### 9.7. Временные зоны

**В БД:** ВСЕГДА UTC

**В алертах:** Можно указать timezone для отображения

```yaml
alerting:
  timezone: "Europe/Moscow"
```

Время в алерте будет показано в указанном часовом поясе.

Часовые пояса указываются стандартными названиями (поддержка встроена в datetime).

### 9.8. AlertChannel

```python
class BaseAlertChannel(ABC):
    @abstractmethod
    def send(self, message: str, destination: Optional[str] = None):
        """Отправка сообщения."""
        pass
```

**Реализации:**
- MattermostChannel - webhook POST (приоритет)
- SlackChannel - webhook POST
- TelegramChannel - Bot API
- EmailChannel - SMTP

### 9.9. Управление алертингом

**По умолчанию:** Запускается весь пайплайн (load → detect → alert)

**Отключение:**
- Через конфиг: `alerting.enabled: false`
- Через CLI: `dtk run --steps load,detect` (без alert)

**Алерт об отсутствии данных:**
```yaml
alerting:
  no_data_alert: true  # отдельный алерт если данных нет
```

Обычно перед алертом отрабатывает load и detect - если после этого данных по точке нет → вызываем no_data алерт.

---

## 10. CLI интерфейс

### 10.1. Основные команды

**Инициализация:**
```bash
dtk init my_project
```

**Запуск:**
```bash
dtk run --select path/to/config.yml
dtk run --select path/to/configs/
dtk run --select tag:10min
dtk run --select tag:10min,tag:critical
```

### 10.2. Селекторы и фильтры

**По тегам:**
```bash
dtk run --select tag:10min,tag:standard
dtk run --select tag:10min --exclude tag:something
```

**Исключения:**
```bash
dtk run --select tag:all --exclude path/to/config.yml
dtk run --select tag:all --exclude path/to/configs/
```

### 10.3. Частичный запуск (--steps)

**Синтаксис:**
```bash
--steps load              # только загрузка
--steps load,detect       # загрузка + детекция
--steps detect            # только детекция
--steps alert             # только алертинг
--steps detect,alert      # детекция + алертинг
```

**По умолчанию:** все процессы (load,detect,alert)

**Валидация:**
- `alert` без `detect` → предупреждение: "Running alerting without detection, using existing results"
- `detect` без `load` → нормально (используем данные из `_dtk_datapoints`)

### 10.4. Перезагрузка данных

**--from DATE:**
```bash
dtk run --select config.yml --from 2024-01-15
```
Удалить данные начиная с даты и перезагрузить.

Применение к разным steps:
- `--steps load --from 2024-01-15` → удалить из `_dtk_datapoints` с даты
- `--steps detect --from 2024-01-15` → удалить из `_dtk_detections` с даты

**--full-refresh:**
```bash
dtk run --select config.yml --full-refresh
```
Удалить все данные и перезагрузить полностью.

**--from и --full-refresh взаимоисключающие!**

### 10.5. Принудительный запуск (--force)

```bash
dtk run --select config.yml --force
```

Игнорировать блокировку `running` статуса в `_dtk_tasks`. При этом `--force`
**сам захватывает блокировку** на время прогона и **освобождает её на выходе**,
поэтому форс-запуск дополнительно лечит ранее зависшую блокировку.

**Можно комбинировать:**
```bash
dtk run --select config.yml --from 2024-01-01 --force
```

### 10.5.1. Сброс зависшей блокировки (dtk unlock)

```bash
dtk unlock --select config.yml
```

Снять зависшую блокировку `running` в `_dtk_tasks` немедленно, не дожидаясь
истечения `timeout_seconds`. Типичная причина зависшей блокировки — **рестарт
БД во время прогона**: процесс не успел записать `completed`/`failed`, и строка
`running` осталась висеть, из-за чего последующие запуски без `--force` падают с
`Failed to acquire lock`. Команда помечает задачу `completed`, не запуская сам
пайплайн. Селекторы — как у `dtk run` (имя, путь, `tag:`).

> Зависшая блокировка также протухает автоматически через `timeout_seconds`
> (см. §13.1) — следующий обычный запуск перезахватит её. `dtk unlock` лишь
> делает это сразу.

### 10.6. Параллелизм (future)

**По умолчанию:** последовательное выполнение

**Параллельное (future):**
```bash
dtk run --select tag:10min --threads 5
```

Заранее закладываем параллельное выполнение, но реализуем позже (некритично).

---

## 11. Конфигурация

### 11.1. Конфиг проекта (detectkit_project.yml)

```yaml
name: "my_analytics_project"
version: "1.0"

# Пути
paths:
  metrics: "metrics"      # папка с конфигами метрик
  sql: "sql"              # папка с SQL файлами
  templates: "templates"  # папка с шаблонами алертов

# Дефолтные таблицы
tables:
  default:
    datapoints: "_dtk_datapoints"
    detections: "_dtk_detections"
    tasks: "_dtk_tasks"

# Дефолтные таймауты (можно переопределить в конфиге метрики)
timeouts:
  load: 3600    # 1 час
  detect: 7200  # 2 часа
  alert: 300    # 5 минут

# Дефолтный профиль (если не указан в конфиге метрики)
default_profile: "clickhouse_prod"
```

### 11.2. Конфиг метрики (metrics/*.yml)

**Полный пример:**
```yaml
metric:
  name: "orders_count_10min"
  profile: "clickhouse_prod"

  tags: ["10min", "orders", "critical"]

  # SQL запрос (или query_file)
  query: |
    SELECT
      toStartOfTenMinutes(created_at) as time_interval,
      count(*) as metric_value,
      toDayOfWeek(time_interval) as day_of_week,
      toHour(time_interval) as hour,
      league_day
    FROM orders
    WHERE created_at >= {{dtk_start_time}} AND created_at < {{dtk_end_time}}
    GROUP BY time_interval, day_of_week, hour
    ORDER BY time_interval

  # Маппинг колонок
  query_columns:
    timestamp: "time_interval"
    metric: "metric_value"
    seasonality: ["day_of_week", "league_day", "hour"]

  # Интервал
  interval: "10min"  # или 600

  # Загрузка
  loading_start_time: "2024-01-01 00:00:00"  # UTC
  loading_batch_size: 1000  # количество точек

  # Детекторы
  detectors:
    - name: "statistical_mad"
      params:
        threshold: 3.0
        window_size: 4320  # 30 дней * 144 точек/день
        start_time: "2024-02-01 00:00:00"
        batch_size: 500
        seasonality_components:
          - "day_of_week"
          - ["league_day", "hour"]

  # Алертинг
  alerting:
    enabled: true
    timezone: "Europe/Moscow"

    channels:
      - type: mattermost
        webhook_url: "${MATTERMOST_WEBHOOK}"  # из env

    conditions:
      min_detectors: 1
      direction: "same"  # "same" / "any" / "up" / "down"
      consecutive_anomalies: 2

    no_data_alert: true

    # Шаблоны
    template_single: |
      Anomaly detected in metric: {metric_name}
      Time: {timestamp} ({timezone})
      Value: {value}
      Confidence interval: [{confidence_lower}, {confidence_upper}]
      Detector: {detector_name}

    template_multiple: |
      Anomaly detected in metric: {metric_name}
      Time: {timestamp} ({timezone})
      Value: {value}
      Detectors triggered: {detectors_list}

  # Переопределение таблиц (опционально)
  tables:
    datapoints: "_dtk_datapoints_sales"
    detections: "_dtk_detections_sales"

  # Переопределение таймаутов (опционально)
  timeouts:
    load: 1800
    detect: 3600
    alert: 120
```

---

## 12. Интервалы

### 12.1. Формат

**Два формата:**
```yaml
interval: 600        # число = секунды (int)
interval: "10min"    # строка = простой формат
```

### 12.2. Поддерживаемые строковые форматы

- Секунды: "30S" или "30s"
- Минуты: "10min" или "10m"
- Часы: "1H" или "1h"
- Дни: "1D" или "1d"

### 12.3. Класс Interval

**Решение:** Custom parser (без pandas)

```python
class Interval:
    """
    Парсер и менеджер интервалов.

    Без внешних зависимостей (только stdlib: re, datetime).
    """

    def __init__(self, value: Union[int, str]):
        self._seconds = self._parse(value)

    def _parse(self, value: Union[int, str]) -> int:
        """Парсинг через regex."""
        if isinstance(value, int):
            return value

        # Regex: (\d+)(S|s|min|m|H|h|D|d)
        # Маппинг единиц в секунды
        ...

    @property
    def seconds(self) -> int:
        """Для БД (Int32)."""
        return self._seconds

    def to_timedelta(self) -> timedelta:
        """Для вычислений."""
        return timedelta(seconds=self._seconds)

    def points_to_timedelta(self, points: int) -> timedelta:
        """Конвертация точек → время."""
        return timedelta(seconds=points * self._seconds)

    def timedelta_to_points(self, td: timedelta) -> int:
        """Конвертация время → точки."""
        return int(td.total_seconds() / self._seconds)

    def floor_timestamp(self, ts: datetime) -> datetime:
        """Округление через epoch и целочисленное деление."""
        epoch = int(ts.timestamp())
        floored = (epoch // self._seconds) * self._seconds
        return datetime.fromtimestamp(floored, tz=timezone.utc)

    def get_last_complete_point(self, now: Optional[datetime] = None) -> datetime:
        """
        Последняя полная точка для алертинга.

        Формула: floor(now, interval) - interval
        """
        if now is None:
            now = datetime.now(timezone.utc)

        floored = self.floor_timestamp(now)
        return floored - self.to_timedelta()

    @classmethod
    def from_seconds(cls, seconds: int) -> 'Interval':
        """
        Создание из БД с красивым форматированием.

        86400 → "1D"
        3600 → "1H"
        60 → "1min"
        иначе → "XS"
        """
        ...
```

---

## 13. Идемпотентность и конкурентность

### 13.1. Таблица _dtk_tasks

**Цель:** Предотвратить параллельный запуск одного процесса.

**Логика:**
```python
def can_start_process(
    metric_name: str,
    detector_id: str,
    process_type: str,
    force: bool = False
) -> bool:
    """
    Проверка возможности запуска процесса.
    """
    task = db_manager.get_task_status(metric_name, detector_id, process_type)

    if not task:
        return True  # первый запуск

    if force:
        return True  # принудительный запуск (--force)

    if task['status'] == 'running':
        elapsed = now() - task['started_at']
        if elapsed > task['timeout_seconds']:
            return True  # зависший процесс (timeout)
        else:
            return False  # еще работает

    if task['status'] in ['completed', 'failed']:
        return True  # можно перезапустить
```

**Timeout:**
- Настраивается в `detectkit_project.yml` (глобально)
- Переопределяется в конфиге метрики (для конкретной метрики)

**CLI флаг --force:**
- Игнорирует проверку `running` статуса
- Обновляет статус на `running`
- Освобождает блокировку на выходе (как обычный запуск) — поэтому форс лечит зависшую блокировку
- Продолжает с `last_processed_timestamp` (или определяет через `get_last_timestamp`)

> **Статус реализации (v0.6.0):** логика выше реализована. `check_lock`/
> `acquire_lock` учитывают `timeout_seconds`: строка `running`, у которой
> `now - started_at > timeout_seconds`, считается зависшей и перезахватывается.
> Таймаут pipeline-блокировки — `PIPELINE_LOCK_TIMEOUT_SECONDS` (3600с). Для
> немедленного сброса есть команда `dtk unlock` (§10.5.1).

### 13.2. Параллельный запуск разных детекторов

**Вопрос:** Можно ли запускать разные детекторы параллельно?

**Ответ:** Да, разные детекторы (разные `detector_id`) могут работать параллельно.

**Блокировка:** Только для триплета (metric_name, detector_id, process_type).

---

## 14. Сложные сценарии

### 14.1. Изменение структуры сезонности

Аналитик добавил новую сезонную колонку:
```yaml
# Было
seasonality: ["day_of_week", "hour"]

# Стало
seasonality: ["day_of_week", "hour", "is_holiday"]
```

**Проблема:** Старые данные не содержат `is_holiday`, структура JSON отличается.

**Решение:** При изменении сезонных колонок → требовать `--full-refresh` (показать warning).

### 14.2. Смена интервала метрики

Аналитик сменил интервал с 10 минут на 5 минут.

**Проблема:** Старые данные с интервалом 10 мин, новые с 5 мин - несовместимость.

**Решение:** Это критическое изменение → требовать изменения `metric.name` (фактически новая метрика).

### 14.3. Несоответствие данных между таблицами

Сценарий:
1. Загрузили данные: 2024-01-01 → 2024-02-01
2. Продетектили 2024-01-01 → 2024-02-01
3. Обнаружили ошибку в SQL, исправили
4. Запустили `--steps load --from 2024-01-15`
5. Проблема: В `_dtk_detections` остались старые результаты для 2024-01-15 → 2024-02-01

**Решение:** Игнорировать (оставить на совести аналитика). Не удалять автоматически.

### 14.4. Очистка старых результатов (future)

В `_dtk_detections` накапливаются результаты за месяцы/годы.

**Решение:** Позже сделаем CLI команду для удаления данных:
```bash
dtk clean --metric orders_count --older-than 2024-01-01
dtk clean --metric orders_count --detector detector123 --older-than 2024-01-01
```

---

## 15. Переменные окружения

**Формат:** `${VAR_NAME}`

**Применение:**
- В конфигах метрик (webhook_url, credentials)
- НЕ в SQL запросах (только Jinja переменные `{{dtk_*}}`)

**Обязательность:**
- Если `${MATTERMOST_WEBHOOK}` не найден → warning + пропуск алертинга

**Пример:**
```yaml
alerting:
  channels:
    - type: mattermost
      webhook_url: "${MATTERMOST_WEBHOOK}"
```

**SQL запросы:**

НЕ используем переменные окружения в SQL! Аналитик сам прописывает нужную БД:
```sql
SELECT *
FROM default.orders  -- хардкод database
WHERE created_at >= {{dtk_start_time}}
```

---

## 16. Инициализация проекта

### 16.1. Команда

```bash
dtk init my_project
```

### 16.2. Создаваемая структура

```
my_project/
├── detectkit_project.yml
├── profiles.yml
├── metrics/
│   └── example_metric.yml
├── sql/
│   └── example_query.sql
└── templates/
    └── .gitkeep
```

**Примерные файлы:** Создаем примеры (example_metric.yml, example_query.sql) для удобства.

**Подключение к БД:** НЕ проверяем при инициализации.

---

## 17. Обработка ошибок

### 17.1. Стратегия

При ошибке в процессе:
```python
try:
    load_metric_data(config)
except Exception as e:
    db_manager.upsert_task_status(
        status='failed',
        error_message=str(e)
    )
    raise
```

**Retry логика:** Сразу `failed`, требовать ручной перезапуск. Без автоматических retry.

**Частичный успех:**
- Если загрузили 5 батчей из 10, на 6-м ошибка
- Статус `failed`, но в `_dtk_datapoints` уже есть 5 батчей
- При перезапуске продолжим с 6-го батча (идемпотентность)

**Уведомления об ошибках:** НЕ отправляем алерт если процесс `failed`. Отправляем только no_data алерт (если настроено).

---

## 18. Производительность

### 18.1. Batch size

**Рекомендации:**
- Загрузка: 1000-10000 точек
- Детекция: 100-1000 точек

**Ограничения:** Определим максимальный batch_size для разных БД и захардкодим лимит.

**Память:**
- Батч 10K точек с 3 сезонными колонками = 50K значений × 8 байт = 400 KB
- Для 100 метрик параллельно (--threads 100) = 40 MB (приемлемо)

### 18.2. Векторизация

**ВАЖНО:** Все операции через numpy - без циклов где возможно.

**Избегать:**
```python
for i in range(len(values)):
    if values[i] > threshold:
        anomalies[i] = True
```

**Предпочитать:**
```python
anomalies = values > threshold
```

---

## 19. Архитектура кода

**ВАЖНО:**
- Код должен быть лаконичным и простым
- Заранее думаем об архитектуре чтобы не получились .py файлы с 2K строк
- Не создавать миллион функций с длинными названиями
- Иногда лучше 1 класс с методами для вариаций работы

**Модульность:**
- Маленькие фокусированные модули
- Избегать файлов > 500-700 строк где возможно

---

## 20. Зависимости

### 20.1. Обязательные

```toml
[project]
dependencies = [
    "numpy>=1.24.0",
    "pydantic>=2.0.0",
    "pyyaml>=6.0",
    "click>=8.0",
    "jinja2>=3.0",
    "orjson>=3.0"
]
```

### 20.2. Опциональные

```toml
[project.optional-dependencies]
# Базы данных
clickhouse = ["clickhouse-driver>=0.2.0"]
postgres = ["psycopg2-binary>=2.9.0"]
mysql = ["pymysql>=1.0.0"]
all-db = ["detectkit[clickhouse,postgres,mysql]"]

# Детекторы
prophet = ["prophet>=1.1.0"]
timesfm = ["timesfm>=0.1.0"]
advanced-detectors = ["detectkit[prophet,timesfm]"]

# Комбинации
all = ["detectkit[all-db,advanced-detectors]"]
```

---

## 21. Этапы разработки

### Phase 1: Core + ClickHouse (MVP)
1. Структура проекта
2. Interval класс
3. Dataclasses (MetricData, DetectionData)
4. Config models (Pydantic)
5. BaseDatabaseManager + TableModel + ClickHouse implementation
6. MetricLoader
7. BaseDetector + статистические детекторы:
   - MAD detector
   - Mean/Std detector
   - IQR detector
   - Manual bounds detector
8. CLI: init, run (минимальная версия)
9. End-to-end тесты

### Phase 2: Алертинг
10. Alerting (orchestrator, decision, channels)
11. Mattermost channel
12. Template rendering

### Phase 3: Продвинутые фичи
13. CLI селекторы (tag:, --exclude)
14. CLI флаги (--from, --full-refresh, --force)
15. Task manager (_dtk_tasks)
16. Параллельное выполнение (--threads)

### Phase 4: Расширение
17. Postgres, MySQL
18. Advanced детекторы (Prophet, TimesFM)
19. Slack, Telegram, Email channels
20. Документация

---

## 22. Документация

**Требования:**
- Каждый детектор: отдельная страница с описанием параметров
- Примеры конфигов для всех сценариев
- Диаграммы архитектуры
- На английском языке

**Структура:**
```
docs/
├── getting-started/
│   ├── installation.md
│   └── quickstart.md
├── guides/
│   ├── configuration.md
│   ├── detectors.md
│   └── alerting.md
├── reference/
│   ├── cli.md
│   ├── detectors/
│   │   ├── mad.md
│   │   ├── zscore.md
│   │   ├── iqr.md
│   │   └── manual.md
│   └── api/
└── examples/
```

---

**КОНЕЦ СПЕЦИФИКАЦИИ**

Все детали из init_plan.md сохранены. Ни одна строчка не проебана.
