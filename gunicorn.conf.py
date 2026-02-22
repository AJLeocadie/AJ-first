# ============================================
# NormaCheck - Gunicorn Configuration OVHcloud
# Optimise pour VPS 2-4 vCPU / 4-8 Go RAM
# ============================================
import os
import multiprocessing

# --- Server ---
bind = f"0.0.0.0:{os.getenv('PORT', '8000')}"
workers = int(os.getenv("NORMACHECK_WORKERS", min(multiprocessing.cpu_count() * 2 + 1, 8)))
worker_class = "uvicorn.workers.UvicornWorker"
worker_connections = 1000

# --- Timeouts ---
# Pas de limite artificielle comme Vercel (60s)
# Les analyses lourdes (20+ fichiers PDF) peuvent prendre du temps
timeout = 600          # 10 minutes max par requete
graceful_timeout = 30  # 30s pour terminer proprement
keepalive = 5

# --- Memory ---
max_requests = 1000        # Recycle worker apres 1000 requetes (previent memory leaks)
max_requests_jitter = 50   # Jitter pour eviter restart simultane

# --- Logging ---
accesslog = os.getenv("NORMACHECK_ACCESS_LOG", "/data/normacheck/logs/access.log")
errorlog = os.getenv("NORMACHECK_ERROR_LOG", "/data/normacheck/logs/error.log")
loglevel = os.getenv("NORMACHECK_LOG_LEVEL", "info")
access_log_format = '%(h)s %(l)s %(u)s %(t)s "%(r)s" %(s)s %(b)s "%(f)s" "%(a)s" %(D)sms'

# --- Process ---
preload_app = True    # Charge l'app une seule fois, partage entre workers
daemon = False
pidfile = "/data/normacheck/normacheck.pid"

# --- Security ---
limit_request_line = 8190
limit_request_fields = 100
limit_request_field_size = 8190

# --- Hooks ---
def on_starting(server):
    """Log au demarrage."""
    server.log.info("NormaCheck starting on OVHcloud VPS...")

def when_ready(server):
    """Log quand pret."""
    server.log.info(f"NormaCheck ready with {workers} workers on {bind}")

def worker_exit(server, worker):
    """Cleanup au shutdown worker."""
    server.log.info(f"Worker {worker.pid} exiting")
