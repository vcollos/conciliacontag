#!/bin/bash
source venv/bin/activate
streamlit run src/core/app.py --server.port 8404 --server.address 0.0.0.0 