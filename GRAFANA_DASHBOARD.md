# 📊 Grafana Dashboard Design для detectkit

> **Документ:** Дизайн дашборда для мониторинга метрик и тестирования детекторов
> **Версия:** 1.0
> **Дата:** 2025-11-10

---

## Общая концепция

**Гибридный дашборд** со **сворачиваемыми строками (Row)** для разных целей:
1. **Production Monitoring** - оперативный мониторинг 10-40 метрик в реальном времени
2. **Metric Deep Dive** - детальный анализ одной метрики с историей
3. **Detector Testing** - сравнение детекторов на одной метрике
4. **System Health** - статус задач, алерты, производительность

**Особенности:**
- Real-time акцент (10мин - 1час интервалы метрик)
- Поддержка разных интервалов у разных метрик
- Только визуализация (алерты уже настроены в detectkit)
- Фильтрация через Grafana встроенный time picker

---

## 🎛️ Variables (фильтры верхнего уровня)

### 1. `$metric_name` - выбор метрики
```sql
-- Query:
SELECT metric_name
FROM _dtk_metrics
WHERE enabled = 1
ORDER BY metric_name
```
- **Type:** Multi-value dropdown (можно выбрать несколько)
- **Include All option:** Yes
- **Purpose:** Основной фильтр для всех панелей

### 2. `$detector_name` - выбор детектора
```sql
-- Query:
SELECT DISTINCT detector_name
FROM _dtk_detections
WHERE metric_name IN ($metric_name)
ORDER BY detector_name
```
- **Type:** Multi-value dropdown
- **Include All option:** Yes
- **Purpose:** Для сравнения детекторов

### 3. `$tag` - фильтр по тегам
```sql
-- Query:
SELECT DISTINCT arrayJoin(JSONExtractArrayRaw(tags)) as tag
FROM _dtk_metrics
WHERE enabled = 1
ORDER BY tag
```
- **Type:** Multi-value dropdown
- **Include All option:** Yes
- **Purpose:** Группировка метрик по категориям

### 4. `$anomaly_severity_min` - минимальная severity для фильтрации
- **Type:** Custom variable
- **Options:** `0`, `2`, `3`, `5`, `10`
- **Default:** `3` (умеренные и выше)

### 5. `$aggregation_interval` - интервал агрегации для графиков
- **Type:** Custom variable
- **Options:**
  - `1 minute` : `toStartOfMinute`
  - `5 minutes` : `toStartOfFiveMinutes`
  - `10 minutes` : `toStartOfTenMinutes`
  - `1 hour` : `toStartOfHour`
  - `1 day` : `toStartOfDay`
- **Default:** `5 minutes`
- **Purpose:** Динамическая агрегация в зависимости от выбранного временного диапазона

---

## 📋 Row 1: **Production Overview** (сворачиваемая)

**Цель:** Быстрый обзор состояния всех метрик + статистика алертов

### Panel 1.1: **Metrics with Recent Anomalies** (Stat)

Количество метрик с аномалиями за выбранный период.

```sql
SELECT
  count(DISTINCT metric_name) as active_metrics
FROM _dtk_detections
WHERE metric_name IN ($metric_name)
  AND is_anomaly = true
  AND $__timeFilter(timestamp)
  AND JSONExtractString(detection_metadata, 'reason') = ''
```

**Пояснение:**
- `$__timeFilter(timestamp)` - стандартный Grafana макрос для фильтрации по времени
- `reason = ''` - исключаем случаи "missing_data" и "insufficient_data" (когда детектор не смог обработать данные)

**Настройки:**
- **Visualization:** Stat panel
- **Thresholds:** 0 (green), 1 (yellow), 3 (red)
- **Size:** Small (3 columns wide)

### Panel 1.2: **Total Anomalies** (Stat)

Общее количество аномалий за период.

```sql
SELECT
  countIf(is_anomaly) as total_anomalies
FROM _dtk_detections
WHERE metric_name IN ($metric_name)
  AND $__timeFilter(timestamp)
  AND JSONExtractString(detection_metadata, 'reason') = ''
```
- **Visualization:** Stat panel with sparkline
- **Size:** Small (3 columns)

### Panel 1.3: **Anomaly Rate** (Stat)

Процент аномальных точек от общего числа.

```sql
SELECT
  countIf(is_anomaly) / count(*) * 100 as anomaly_rate_pct
FROM _dtk_detections
WHERE metric_name IN ($metric_name)
  AND $__timeFilter(timestamp)
  AND JSONExtractString(detection_metadata, 'reason') = ''
```
- **Visualization:** Stat panel (%)
- **Thresholds:** 0-1% (green), 1-5% (yellow), >5% (red)
- **Size:** Small (3 columns)

### Panel 1.4: **Last Alert Sent** (Stat)

Когда был отправлен последний алерт.

```sql
SELECT
  max(last_alert_sent) as last_alert
FROM _dtk_tasks
WHERE metric_name IN ($metric_name)
  AND alert_count > 0
```
- **Visualization:** Stat panel (time ago)
- **Size:** Small (3 columns)

### Panel 1.5: **Metrics Heatmap** (Heatmap)

Тепловая карта аномалий по метрикам и времени с динамической агрегацией.

```sql
SELECT
  ${aggregation_interval}(timestamp) as time,
  metric_name,
  countIf(is_anomaly) as anomaly_count
FROM _dtk_detections
WHERE metric_name IN ($metric_name)
  AND $__timeFilter(timestamp)
  AND JSONExtractString(detection_metadata, 'reason') = ''
GROUP BY time, metric_name
ORDER BY time, metric_name
```

**Пояснение:**
- `${aggregation_interval}` - переменная с функцией агрегации (toStartOfMinute, toStartOfHour и т.д.)
- При выборе большого периода (30 дней) пользователь должен выбрать `1 hour` или `1 day` в `$aggregation_interval`
- Для коротких периодов (1 час) - `1 minute` или `5 minutes`

**Настройки:**
- **Visualization:** Heatmap (строки = метрики, цвет = количество аномалий)
- **Size:** Full width
- **Purpose:** Быстро увидеть какие метрики аномальные и когда

**Рекомендации по использованию:**
- Период < 6 часов → aggregation_interval = "1 minute"
- Период 6-24 часа → aggregation_interval = "5 minutes"
- Период 1-7 дней → aggregation_interval = "1 hour"
- Период > 7 дней → aggregation_interval = "1 day"

### Panel 1.6: **Anomaly Timeline (All Metrics)** (Time Series)

График количества аномалий во времени по всем метрикам.

```sql
SELECT
  ${aggregation_interval}(timestamp) as time,
  metric_name,
  countIf(is_anomaly) as anomaly_count
FROM _dtk_detections
WHERE metric_name IN ($metric_name)
  AND $__timeFilter(timestamp)
  AND JSONExtractString(detection_metadata, 'reason') = ''
GROUP BY time, metric_name
ORDER BY time
```
- **Visualization:** Time Series (stacked bars)
- **Size:** Full width
- **Purpose:** Временной график аномалий по всем метрикам

---

## 📊 Row 2: **Metric Deep Dive** (сворачиваемая)

**Цель:** Детальный анализ одной выбранной метрики с историей

> **ВАЖНО:** Для корректной работы панелей в этой строке выберите **ОДНУ метрику** в `$metric_name`

### Panel 2.1: **Metric Info** (Table)

Конфигурация выбранной метрики.

```sql
SELECT
  metric_name,
  description,
  interval,
  is_alert_enabled,
  consecutive_anomalies,
  min_detectors,
  direction,
  timezone,
  JSONExtractArrayRaw(tags) as tags
FROM _dtk_metrics
WHERE metric_name = '$metric_name'
LIMIT 1
```
- **Visualization:** Table (vertical mode)
- **Size:** Half width
- **Purpose:** Показать конфигурацию метрики

### Panel 2.2: **Alert Statistics** (Table)

Статистика по алертам для метрики.

```sql
SELECT
  metric_name,
  alert_count,
  last_alert_sent,
  dateDiff('minute', last_alert_sent, now()) as minutes_since_alert
FROM _dtk_tasks
WHERE metric_name = '$metric_name'
  AND process_type = 'pipeline'
ORDER BY last_alert_sent DESC
LIMIT 1
```
- **Visualization:** Table
- **Size:** Half width

### Panel 2.3: **Metric Value + Anomalies + Confidence Bands** (Time Series)

**🔥 Главная панель для production мониторинга!**

График метрики с confidence bounds и маркерами аномалий.

```sql
SELECT
  dp.timestamp as time,
  dp.value as "Metric Value",
  anyIf(det.confidence_lower, det.detector_name = '$detector_name' OR '$detector_name' = 'All') as "Lower Bound",
  anyIf(det.confidence_upper, det.detector_name = '$detector_name' OR '$detector_name' = 'All') as "Upper Bound",
  anyIf(if(det.is_anomaly, dp.value, NULL), det.detector_name = '$detector_name' OR '$detector_name' = 'All') as "Anomaly"
FROM _dtk_datapoints dp
LEFT JOIN _dtk_detections det
  ON dp.metric_name = det.metric_name
  AND dp.timestamp = det.timestamp
WHERE dp.metric_name = '$metric_name'
  AND $__timeFilter(dp.timestamp)
GROUP BY dp.timestamp, dp.value
ORDER BY dp.timestamp
```

**Настройки:**
- **Visualization:** Time Series
- **Series overrides:**
  - `Metric Value` - Line (width: 2, blue)
  - `Lower Bound` - Line (dashed, gray, fill below to Upper Bound)
  - `Upper Bound` - Line (dashed, gray)
  - `Anomaly` - Points (red, size: 8)
- **Size:** Full width, tall (6-8 units)
- **Purpose:** **ОСНОВНОЙ график для мониторинга метрики**

### Panel 2.4: **Missing Data Intervals** (Bar Chart)

Интервалы с отсутствующими данными.

```sql
SELECT
  ${aggregation_interval}(timestamp) as time,
  countIf(isNull(value)) as missing_points
FROM _dtk_datapoints
WHERE metric_name = '$metric_name'
  AND $__timeFilter(timestamp)
GROUP BY time
HAVING missing_points > 0
ORDER BY time
```
- **Visualization:** Bar Chart
- **Size:** Half width
- **Purpose:** Видеть где были пропуски данных

### Panel 2.5: **Anomaly Severity Distribution** (Histogram)

Распределение аномалий по уровню severity.

```sql
SELECT
  round(JSONExtractFloat(detection_metadata, 'severity'), 1) as severity_bucket,
  count(*) as count
FROM _dtk_detections
WHERE metric_name = '$metric_name'
  AND is_anomaly = true
  AND $__timeFilter(timestamp)
  AND JSONExtractString(detection_metadata, 'reason') = ''
GROUP BY severity_bucket
ORDER BY severity_bucket
```
- **Visualization:** Bar Chart
- **Size:** Half width
- **Purpose:** Распределение severity аномалий (сколько легких, средних, тяжелых)

### Panel 2.6: **Recent Anomalies Table** (Table)

Детальная таблица всех аномалий с метаданными.

```sql
SELECT
  timestamp,
  detector_name,
  value,
  confidence_lower,
  confidence_upper,
  JSONExtractString(detection_metadata, 'direction') as direction,
  round(JSONExtractFloat(detection_metadata, 'severity'), 2) as severity,
  round(JSONExtractFloat(detection_metadata, 'distance'), 2) as distance
FROM _dtk_detections
WHERE metric_name = '$metric_name'
  AND is_anomaly = true
  AND $__timeFilter(timestamp)
  AND JSONExtractFloat(detection_metadata, 'severity') >= $anomaly_severity_min
ORDER BY timestamp DESC
LIMIT 100
```
- **Visualization:** Table (sortable, filterable)
- **Size:** Full width
- **Purpose:** Детальная таблица всех аномалий с метаданными

### Panel 2.7: **Anomaly Direction Breakdown** (Pie Chart)

Распределение аномалий по направлению (вверх/вниз).

```sql
SELECT
  JSONExtractString(detection_metadata, 'direction') as direction,
  count(*) as count
FROM _dtk_detections
WHERE metric_name = '$metric_name'
  AND is_anomaly = true
  AND $__timeFilter(timestamp)
  AND JSONExtractString(detection_metadata, 'reason') = ''
GROUP BY direction
```
- **Visualization:** Pie Chart
- **Size:** Half width
- **Purpose:** Видеть преобладающее направление аномалий (спайки vs провалы)

### Panel 2.8: **Anomaly Rate Over Time** (Time Series)

Динамика частоты аномалий во времени.

```sql
SELECT
  ${aggregation_interval}(timestamp) as time,
  countIf(is_anomaly) / count(*) * 100 as anomaly_rate_pct
FROM _dtk_detections
WHERE metric_name = '$metric_name'
  AND $__timeFilter(timestamp)
  AND JSONExtractString(detection_metadata, 'reason') = ''
GROUP BY time
ORDER BY time
```
- **Visualization:** Time Series (area chart)
- **Size:** Half width
- **Purpose:** Видеть как менялась частота аномалий во времени

---

## 🔬 Row 3: **Detector Comparison** (сворачиваемая)

**Цель:** Сравнить разные детекторы на одной метрике для выбора лучшего

> **ВАЖНО:** Для корректной работы выберите **ОДНУ метрику** в `$metric_name` и **несколько детекторов** в `$detector_name`

### Panel 3.1: **Detector Statistics** (Table)

Статистика по каждому детектору: сколько нашел аномалий, средняя severity.

```sql
SELECT
  detector_name,
  count(*) as total_points,
  countIf(is_anomaly) as anomalies,
  round(countIf(is_anomaly) / count(*) * 100, 2) as anomaly_rate_pct,
  round(avg(JSONExtractFloat(detection_metadata, 'severity')), 2) as avg_severity,
  round(quantile(0.95)(JSONExtractFloat(detection_metadata, 'severity')), 2) as p95_severity
FROM _dtk_detections
WHERE metric_name = '$metric_name'
  AND $__timeFilter(timestamp)
  AND JSONExtractString(detection_metadata, 'reason') = ''
GROUP BY detector_name
ORDER BY anomaly_rate_pct DESC
```
- **Visualization:** Table (sortable)
- **Size:** Full width
- **Purpose:** **Главная таблица для выбора детектора** - показывает кто сколько аномалий нашел

### Panel 3.2: **Detector Comparison Timeline** (Time Series)

Временной график показывающий когда каждый детектор детектил аномалии.

```sql
SELECT
  ${aggregation_interval}(timestamp) as time,
  detector_name,
  countIf(is_anomaly) as anomalies
FROM _dtk_detections
WHERE metric_name = '$metric_name'
  AND detector_name IN ($detector_name)
  AND $__timeFilter(timestamp)
  AND JSONExtractString(detection_metadata, 'reason') = ''
GROUP BY time, detector_name
ORDER BY time
```
- **Visualization:** Time Series (stacked area или bars)
- **Size:** Full width
- **Purpose:** Увидеть когда каждый детектор детектил аномалии (consensus vs. noise)

### Panel 3.3: **Confidence Bands Comparison** (Time Series)

Показывает все детекторы с их confidence bands на одном графике.

```sql
SELECT
  det.timestamp as time,
  dp.value as "Metric Value",
  -- Динамически создаем серии для каждого детектора
  maxIf(det.confidence_lower, det.detector_name = 'MADDetector') as "MAD Lower",
  maxIf(det.confidence_upper, det.detector_name = 'MADDetector') as "MAD Upper",
  maxIf(det.confidence_lower, det.detector_name = 'ZScoreDetector') as "ZScore Lower",
  maxIf(det.confidence_upper, det.detector_name = 'ZScoreDetector') as "ZScore Upper",
  maxIf(det.confidence_lower, det.detector_name = 'IQRDetector') as "IQR Lower",
  maxIf(det.confidence_upper, det.detector_name = 'IQRDetector') as "IQR Upper"
FROM _dtk_detections det
LEFT JOIN _dtk_datapoints dp
  ON det.metric_name = dp.metric_name
  AND det.timestamp = dp.timestamp
WHERE det.metric_name = '$metric_name'
  AND det.detector_name IN ($detector_name)
  AND $__timeFilter(det.timestamp)
GROUP BY det.timestamp, dp.value
ORDER BY det.timestamp
```

**Примечание:**
Если нужно динамически создавать серии для всех выбранных детекторов, лучше использовать отдельные запросы в Grafana (Transformation: Outer join).

**Настройки:**
- **Visualization:** Time Series
- **Series overrides:**
  - `Metric Value` - Solid line (blue, bold)
  - MAD bounds - Green dashed
  - ZScore bounds - Orange dashed
  - IQR bounds - Purple dashed
- **Size:** Full width, tall
- **Purpose:** **Визуально сравнить насколько чувствительны разные детекторы**

### Panel 3.4: **Detector Consensus** (Table)

Показывает моменты когда несколько детекторов согласны.

```sql
SELECT
  timestamp,
  groupArray(detector_name) as agreeing_detectors,
  countIf(is_anomaly) as votes,
  count(*) as total_detectors,
  round(countIf(is_anomaly) / count(*) * 100, 0) as consensus_pct,
  anyIf(value, is_anomaly) as anomaly_value
FROM _dtk_detections
WHERE metric_name = '$metric_name'
  AND detector_name IN ($detector_name)
  AND $__timeFilter(timestamp)
  AND JSONExtractString(detection_metadata, 'reason') = ''
GROUP BY timestamp, value
HAVING votes >= 2  -- Минимум 2 детектора согласны
ORDER BY timestamp DESC
LIMIT 100
```
- **Visualization:** Table
- **Size:** Full width
- **Purpose:** Найти **настоящие аномалии** где согласны несколько детекторов

### Panel 3.5: **False Positives Analysis** (Bar Chart)

Аномалии которые нашел только один детектор (потенциально ложные срабатывания).

```sql
SELECT
  detector_name,
  count(*) as solo_anomalies
FROM (
  SELECT
    timestamp,
    detector_name,
    countIf(is_anomaly) OVER (PARTITION BY timestamp) as total_votes
  FROM _dtk_detections
  WHERE metric_name = '$metric_name'
    AND detector_name IN ($detector_name)
    AND $__timeFilter(timestamp)
    AND is_anomaly = true
)
WHERE total_votes = 1  -- Только этот детектор нашел аномалию
GROUP BY detector_name
ORDER BY solo_anomalies DESC
```
- **Visualization:** Bar Chart (horizontal)
- **Size:** Half width
- **Purpose:** Показать какой детектор дает больше всего **уникальных** (возможно ложных) алертов

### Panel 3.6: **Severity Comparison by Detector** (Bar Chart)

Распределение severity по детекторам.

```sql
SELECT
  detector_name,
  quantile(0.5)(JSONExtractFloat(detection_metadata, 'severity')) as median_severity,
  quantile(0.95)(JSONExtractFloat(detection_metadata, 'severity')) as p95_severity,
  max(JSONExtractFloat(detection_metadata, 'severity')) as max_severity
FROM _dtk_detections
WHERE metric_name = '$metric_name'
  AND detector_name IN ($detector_name)
  AND is_anomaly = true
  AND $__timeFilter(timestamp)
  AND JSONExtractString(detection_metadata, 'reason') = ''
GROUP BY detector_name
ORDER BY median_severity DESC
```
- **Visualization:** Bar Chart (grouped)
- **Size:** Half width
- **Purpose:** Сравнить распределение severity между детекторами

---

## ⚙️ Row 4: **System Health** (сворачиваемая)

**Цель:** Мониторинг самой системы detectkit (задачи, производительность, ошибки)

### Panel 4.1: **Running Tasks** (Stat)

Количество задач в статусе "running".

```sql
SELECT
  count(*) as running_tasks
FROM _dtk_tasks
WHERE status = 'running'
```
- **Visualization:** Stat
- **Threshold:** 0 (green), >10 (yellow), >20 (red)
- **Size:** Small

### Panel 4.2: **Failed Tasks (Period)** (Stat)

Количество упавших задач за выбранный период.

```sql
SELECT
  count(*) as failed_tasks
FROM _dtk_tasks
WHERE status = 'failed'
  AND $__timeFilter(updated_at)
```
- **Visualization:** Stat
- **Threshold:** 0 (green), >0 (red)
- **Size:** Small

### Panel 4.3: **Average Task Duration** (Stat)

Средняя продолжительность выполнения задач.

```sql
SELECT
  avg(dateDiff('second', started_at, updated_at)) as avg_duration_sec
FROM _dtk_tasks
WHERE status = 'completed'
  AND $__timeFilter(updated_at)
```
- **Visualization:** Stat (seconds)
- **Size:** Small

### Panel 4.4: **Completed Tasks** (Stat)

Количество успешно завершенных задач.

```sql
SELECT
  count(*) as completed_tasks
FROM _dtk_tasks
WHERE status = 'completed'
  AND $__timeFilter(updated_at)
```
- **Visualization:** Stat
- **Size:** Small

### Panel 4.5: **Task Execution Timeline** (Time Series)

График запуска задач во времени.

```sql
SELECT
  ${aggregation_interval}(started_at) as time,
  process_type,
  count(*) as tasks_started
FROM _dtk_tasks
WHERE $__timeFilter(started_at)
GROUP BY time, process_type
ORDER BY time
```
- **Visualization:** Time Series (stacked bars)
- **Size:** Full width
- **Purpose:** Видеть когда запускались задачи

### Panel 4.6: **Task Status by Metric** (Table)

Статус всех задач с детализацией.

```sql
SELECT
  metric_name,
  process_type,
  status,
  started_at,
  updated_at,
  dateDiff('second', started_at, updated_at) as duration_sec,
  last_processed_timestamp,
  error_message
FROM _dtk_tasks
WHERE $__timeFilter(updated_at)
ORDER BY updated_at DESC
LIMIT 100
```
- **Visualization:** Table (color by status)
- **Size:** Full width
- **Purpose:** Детальный статус всех задач

### Panel 4.7: **Error Log** (Table)

История ошибок выполнения задач.

```sql
SELECT
  updated_at,
  metric_name,
  process_type,
  error_message
FROM _dtk_tasks
WHERE status = 'failed'
  AND $__timeFilter(updated_at)
ORDER BY updated_at DESC
LIMIT 100
```
- **Visualization:** Table (expandable rows for long errors)
- **Size:** Full width
- **Purpose:** История ошибок

### Panel 4.8: **Detection Lag** (Time Series)

Отставание обработки от реального времени (lag).

```sql
SELECT
  ${aggregation_interval}(updated_at) as time,
  metric_name,
  avg(dateDiff('minute', last_processed_timestamp, updated_at)) as avg_lag_minutes
FROM _dtk_tasks
WHERE process_type = 'detect'
  AND last_processed_timestamp IS NOT NULL
  AND $__timeFilter(updated_at)
GROUP BY time, metric_name
ORDER BY time
```
- **Visualization:** Time Series
- **Size:** Full width
- **Purpose:** Видеть если какая-то метрика отстала в обработке

---

## 🎨 Dashboard Settings

### General Settings
- **Name:** `detectkit - Production Monitoring`
- **Refresh:** `30s` (для real-time мониторинга)
- **Time range:** `Last 1 hour` (default)
- **Timezone:** `UTC` (или ваш local timezone)

### Row Collapse Defaults
- **Row 1 (Production Overview):** Expanded (главная для prod)
- **Row 2 (Metric Deep Dive):** Collapsed (открываем по необходимости)
- **Row 3 (Detector Comparison):** Collapsed (для тестирования)
- **Row 4 (System Health):** Collapsed (проверяем при проблемах)

### Panel Linking
- При клике на метрику в Production Overview → автоматически открывается Row 2 с этой метрикой
- При клике на аномалию → переход к Recent Anomalies Table с фильтром по времени

---

## 🚀 Quick Start Queries

### Все метрики с активными аномалиями (для Variable)
```sql
SELECT DISTINCT metric_name
FROM _dtk_detections
WHERE is_anomaly = true
  AND timestamp >= now() - interval 10 minute
ORDER BY metric_name
```

### Топ-10 "шумных" метрик (для приоритезации настройки)
```sql
SELECT
  metric_name,
  countIf(is_anomaly) as anomalies_last_24h,
  count(*) as total_points,
  round(countIf(is_anomaly) / count(*) * 100, 2) as anomaly_rate
FROM _dtk_detections
WHERE timestamp >= now() - interval 24 hour
  AND JSONExtractString(detection_metadata, 'reason') = ''
GROUP BY metric_name
ORDER BY anomalies_last_24h DESC
LIMIT 10
```

---

## 📝 Recommendations

### Для Production Monitoring (Row 1 + Row 2):
1. **Держите открытой Row 1** на большом экране - она дает полную картину
2. **Настройте refresh 30 секунд** для real-time мониторинга
3. **Используйте тэги** для группировки критичных метрик (production, api, critical)
4. **Panel 2.3 (Metric Value + Anomalies)** - главный график, сделайте его большим
5. **Выбирайте aggregation_interval** исходя из временного диапазона:
   - < 6 часов → "1 minute"
   - 6-24 часа → "5 minutes"
   - 1-7 дней → "1 hour"
   - > 7 дней → "1 day"

### Для Detector Testing (Row 3):
1. **Выберите ОДНУ метрику** через $metric_name
2. **Выберите несколько детекторов** через $detector_name (например, MAD + ZScore + IQR)
3. **Panel 3.1 (Detector Statistics)** покажет кто нашел сколько аномалий
4. **Panel 3.3 (Confidence Bands)** покажет визуально кто более/менее чувствительный
5. **Panel 3.4 (Consensus)** покажет настоящие аномалии где все согласны
6. **Выбирайте детектор** с балансом: не слишком шумный (много solo_anomalies), но и не слишком тихий

### Performance Tips:
- Для 10-40 метрик все запросы будут быстрые
- Используйте `$__timeFilter()` - Grafana оптимизирует временные фильтры
- ClickHouse ReplacingMergeTree может давать дубли - добавьте `FINAL` если видите странности:
  ```sql
  FROM _dtk_detections FINAL
  ```
- Для heatmap и timeline обязательно используйте `${aggregation_interval}` для адаптивной агрегации
- При больших временных диапазонах (> 7 дней) Grafana может сам применить downsampling

### О фильтрации `reason`:
- `JSONExtractString(detection_metadata, 'reason') = ''` - исключает случаи когда детектор не смог обработать данные:
  - `'missing_data'` - данные отсутствуют (value IS NULL)
  - `'insufficient_data'` - недостаточно точек для расчета (меньше min_samples)
  - `'insufficient_group_data'` - недостаточно точек в seasonality группе
- Без этого фильтра в графики попадут "технические" записи где is_anomaly=false по техническим причинам

---

## 🎯 Summary

**Структура:**
- 4 сворачиваемые строки (Rows)
- ~26 панелей total
- 5 Variables для гибкой фильтрации

**Use Cases:**
1. **Production monitoring** → Row 1 + Row 2.3 открыты → видно все метрики + детали по выбранной
2. **Detector testing** → Row 3 открыта → сравнение детекторов на исторических данных
3. **Troubleshooting** → Row 4 открыта → смотрим ошибки и статус задач

**Key Panels:**
- **Panel 1.5 (Metrics Heatmap)** - быстрый обзор всех метрик
- **Panel 2.3 (Metric + Confidence)** - главный график для prod
- **Panel 3.3 (Detector Comparison)** - главный для выбора детектора

**Важные моменты:**
- ✅ Используется `$__timeFilter()` вместо хардкодных интервалов
- ✅ Динамическая агрегация через `${aggregation_interval}`
- ✅ Фильтрация технических записей через `reason = ''`
- ✅ Поддержка метрик с разными интервалами
- ✅ Адаптивность к разным временным диапазонам

---

## 🔄 Версионирование

- **v1.0** (2025-11-10): Первая версия с исправлениями
  - Использование `$__timeFilter()` вместо хардкодных интервалов
  - Добавлена переменная `${aggregation_interval}` для адаптивной агрегации
  - Объяснение фильтрации `reason` для исключения технических записей
  - Убраны графики с хардкодной сезонностью
  - Рекомендации по использованию для разных временных диапазонов
