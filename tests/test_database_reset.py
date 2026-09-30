from src import database as db


def test_reset_database_clears_all_tenants(tmp_path):
    path = str(tmp_path / "reset.db")
    db.init_db(path)
    record = db.CompanyRecord(name="Test", tier="small", sanctioned_load_kw=100)
    cid, _ = db.create_company(record, path)
    assert db.count_companies(path) == 1
    db.reset_database(path)
    assert db.count_companies(path) == 0
    db.dispose_engine(path)
