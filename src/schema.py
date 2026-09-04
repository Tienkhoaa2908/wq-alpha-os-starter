from sqlalchemy import create_engine, Column, Integer, Float, Text, DateTime, UniqueConstraint
from sqlalchemy.orm import declarative_base, sessionmaker
from datetime import datetime
from pathlib import Path

Base = declarative_base()
DB_PATH = Path("data/db/wq_alpha_os.sqlite")


class Dataset(Base):
    __tablename__ = "datasets"
    id = Column(Integer, primary_key=True)
    category = Column(Text)
    dataset_name = Column(Text)
    region = Column(Text)
    delay = Column(Integer)
    universe = Column(Text)
    fields_count = Column(Integer)
    coverage = Column(Float)
    date_coverage = Column(Float)
    value_score = Column(Float)
    alphas_count = Column(Integer)
    last_field_added = Column(Text)
    source_file = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("category", "dataset_name", "region", "delay", "universe"),)


class Field(Base):
    __tablename__ = "fields"
    id = Column(Integer, primary_key=True)
    field_name = Column(Text)
    dataset_name = Column(Text)
    category = Column(Text)
    description = Column(Text)
    field_type = Column(Text)
    coverage = Column(Float)
    date_coverage = Column(Float)
    alphas_count = Column(Integer)
    date_added = Column(Text)
    source_file = Column(Text)
    field_role = Column(Text)
    economic_theme = Column(Text)
    alpha_family = Column(Text)
    expected_turnover = Column(Text)
    missing_risk = Column(Text)
    recommended_operators = Column(Text)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("field_name", "dataset_name", "category"),)


class Operator(Base):
    __tablename__ = "operators"
    id = Column(Integer, primary_key=True)
    operator_name = Column(Text)
    category = Column(Text)
    level = Column(Text)
    signature = Column(Text)
    description = Column(Text)
    use_case = Column(Text)
    expected_effect = Column(Text)
    source_file = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)
    __table_args__ = (UniqueConstraint("operator_name", "signature"),)


class AlphaCandidate(Base):
    __tablename__ = "alpha_candidates"
    id = Column(Integer, primary_key=True)
    expression = Column(Text, unique=True)
    family = Column(Text)
    fields_used = Column(Text)
    operators_used = Column(Text)
    hypothesis = Column(Text)
    expected_turnover = Column(Text)
    expected_risk = Column(Text)
    status = Column(Text, default="new")
    created_at = Column(DateTime, default=datetime.utcnow)


class Experiment(Base):
    __tablename__ = "experiments"
    id = Column(Integer, primary_key=True)
    alpha_expression = Column(Text)
    region = Column(Text)
    universe = Column(Text)
    delay = Column(Integer)
    decay = Column(Integer)
    truncation = Column(Float)
    neutralization = Column(Text)
    pasteurization = Column(Text)
    sharpe = Column(Float)
    fitness = Column(Float)
    turnover = Column(Float)
    returns = Column(Float)
    drawdown = Column(Float)
    margin = Column(Float)
    subuniverse_sharpe = Column(Float)
    pass_count = Column(Integer)
    fail_count = Column(Integer)
    fail_reasons = Column(Text)
    notes = Column(Text)
    created_at = Column(DateTime, default=datetime.utcnow)


def make_engine(db_path: str | None = None):
    if db_path is None:
        db_path = str(DB_PATH)
    Path(db_path).parent.mkdir(parents=True, exist_ok=True)
    engine = create_engine(f"sqlite:///{db_path}", future=True)
    Base.metadata.create_all(engine)
    return engine


def make_session(db_path: str | None = None):
    engine = make_engine(db_path)
    return sessionmaker(bind=engine, future=True)
