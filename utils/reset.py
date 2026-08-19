from sqlalchemy import create_engine, text

engine = create_engine('sqlite:///./bizinsight.db')
with engine.connect() as conn:
    conn.execute(text("UPDATE documents SET process='PENDING', faiss_ids=NULL"))
    conn.commit()
    print('All documents reset to PENDING')