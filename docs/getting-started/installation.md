# Installation

This guide covers installing detectkit and its dependencies.

## Requirements

- **Python**: 3.10 or higher
- **pip**: Latest version recommended
- **Database**: ClickHouse, PostgreSQL, or MySQL (at least one required)

## Basic Installation

Install detectkit from PyPI:

```bash
pip install detectkit
```

This installs:
- Core detectkit library
- Basic statistical detectors (MAD, Z-Score, IQR, Manual Bounds)
- CLI tool (`dtk` command)
- numpy, pydantic, click dependencies

## Database Drivers

detectkit requires a database driver to be installed separately.

### ClickHouse (Recommended)

```bash
pip install detectkit[clickhouse]
```

Or install driver manually:

```bash
pip install clickhouse-driver
```

**Supported versions**: ClickHouse 20.3+

### PostgreSQL

```bash
pip install detectkit[postgres]
```

Or install driver manually:

```bash
pip install psycopg2-binary
```

**Supported versions**: PostgreSQL 12+

### MySQL

```bash
pip install detectkit[mysql]
```

Or install driver manually:

```bash
pip install mysql-connector-python
```

**Supported versions**: MySQL 8.0+

### Multiple Databases

Install drivers for all databases you'll use:

```bash
pip install detectkit[clickhouse,postgres,mysql]
```

## Advanced Detectors (Optional)

### Prophet Detector

Time-series forecasting with Facebook Prophet:

```bash
pip install detectkit[prophet]
```

**Note**: Prophet has heavy dependencies (pystan, fbprophet). Only install if needed.

### TimesFM Detector

Google's TimesFM model for time-series:

```bash
pip install detectkit[timesfm]
```

**Note**: Requires TensorFlow dependencies.

### All Advanced Detectors

```bash
pip install detectkit[all]
```

## Development Installation

For contributing to detectkit:

### 1. Clone Repository

```bash
git clone https://github.com/alexeiveselov92/detectkit.git
cd detectkit
```

### 2. Create Virtual Environment

```bash
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate
```

### 3. Install in Editable Mode

```bash
pip install -e .[dev]
```

This installs:
- detectkit in editable mode
- All database drivers
- Development tools (pytest, black, ruff)

### 4. Run Tests

```bash
pytest
```

## Verifying Installation

Check that detectkit is installed correctly:

```bash
dtk --version
```

Expected output:

```
dtk, version 0.3.0
```

## Upgrading

Upgrade to the latest version:

```bash
pip install --upgrade detectkit
```

## Uninstalling

Remove detectkit:

```bash
pip uninstall detectkit
```

## Docker Installation (Optional)

Create a Dockerfile for containerized deployment:

```dockerfile
FROM python:3.11-slim

# Install detectkit with ClickHouse driver
RUN pip install detectkit[clickhouse]

# Copy project files
COPY . /app
WORKDIR /app

# Run detectkit
CMD ["dtk", "run", "--select", "*"]
```

Build and run:

```bash
docker build -t my-detectkit .
docker run -v $(pwd):/app my-detectkit
```

## Troubleshooting

### ImportError: No module named 'detectkit'

**Solution**: Ensure detectkit is installed in the active Python environment:

```bash
pip list | grep detectkit
```

### ClickHouse driver not found

**Solution**: Install ClickHouse driver:

```bash
pip install clickhouse-driver
```

### Permission denied on Linux

**Solution**: Install with --user flag:

```bash
pip install --user detectkit
```

### SSL certificate errors

**Solution**: Upgrade pip and certifi:

```bash
pip install --upgrade pip certifi
```

### Old version installed

**Solution**: Force reinstall:

```bash
pip install --force-reinstall detectkit
```

## Next Steps

After installation:

1. [Quickstart Guide](quickstart.md) - Create your first metric
2. [Configuration Guide](../guides/configuration.md) - Learn configuration options
3. [CLI Reference](../reference/cli.md) - Explore CLI commands

## Getting Help

- **Documentation**: https://github.com/alexeiveselov92/detectkit
- **Issues**: https://github.com/alexeiveselov92/detectkit/issues
- **PyPI**: https://pypi.org/project/detectkit/
