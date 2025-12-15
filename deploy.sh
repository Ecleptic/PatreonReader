#!/bin/bash
#
# PatreonReader Docker Deployment Script
# Single entry point for all Docker operations
#
# Usage: ./deploy.sh [command]
#
# Commands:
#   deploy       - Full deployment (stop, rebuild, verify, start)
#   build        - Incremental build only
#   rebuild      - Force rebuild with --no-cache
#   clean-deploy - Full cleanup including images, then fresh deploy
#   start        - Start services
#   stop         - Stop services
#   restart      - Restart services
#   status       - Show container status
#   logs         - View logs (last 100 lines)
#   logs-follow  - Follow logs in real-time
#   verify       - Run health checks
#   shell        - Open shell in running container
#   cleanup      - Remove containers, images, prune resources
#   help         - Show this help message
#

set -e

# =============================================================================
# Configuration
# =============================================================================

PROJECT_NAME="patreon-reader"
SERVICE_NAME="patreon-reader"
COMPOSE_FILE="docker-compose.yml"
REQUIRED_FILES=("Dockerfile" "docker-compose.yml" "requirements.txt" "api_server.py")
HEALTH_CHECK_URL="http://localhost:8000/api/health"
HEALTH_CHECK_RETRIES=30
HEALTH_CHECK_DELAY=2

# =============================================================================
# Colors
# =============================================================================

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

# =============================================================================
# Logging Functions
# =============================================================================

info() {
    echo -e "${BLUE}[INFO]${NC} $1"
}

success() {
    echo -e "${GREEN}[SUCCESS]${NC} $1"
}

warning() {
    echo -e "${YELLOW}[WARNING]${NC} $1"
}

error() {
    echo -e "${RED}[ERROR]${NC} $1"
}

header() {
    echo ""
    echo -e "${CYAN}========================================${NC}"
    echo -e "${CYAN} $1${NC}"
    echo -e "${CYAN}========================================${NC}"
    echo ""
}

# =============================================================================
# Prerequisite Checks
# =============================================================================

check_docker() {
    if ! command -v docker &> /dev/null; then
        error "Docker is not installed. Please install Docker first."
        exit 1
    fi

    if ! docker info &> /dev/null; then
        error "Docker daemon is not running. Please start Docker."
        exit 1
    fi

    if ! command -v docker-compose &> /dev/null && ! docker compose version &> /dev/null; then
        error "Docker Compose is not available. Please install Docker Compose."
        exit 1
    fi
}

check_required_files() {
    local missing_files=()
    
    for file in "${REQUIRED_FILES[@]}"; do
        if [[ ! -f "$file" ]]; then
            missing_files+=("$file")
        fi
    done

    if [[ ${#missing_files[@]} -gt 0 ]]; then
        error "Missing required files:"
        for file in "${missing_files[@]}"; do
            echo "  - $file"
        done
        exit 1
    fi
}

check_env_file() {
    if [[ ! -f ".env" ]]; then
        if [[ -f ".env.example" ]]; then
            warning ".env file not found. Creating from .env.example..."
            cp .env.example .env
            warning "Please edit .env with your configuration before deploying."
            info "Required settings:"
            echo "  - API_TOKEN: Your API authentication token"
            echo "  - PATREON_SESSION_ID: Your Patreon session cookie"
            return 1
        else
            warning ".env file not found. Using default configuration."
        fi
    fi
    return 0
}

run_checks() {
    info "Running prerequisite checks..."
    check_docker
    check_required_files
    success "All prerequisites met"
}

# =============================================================================
# Docker Compose Wrapper
# =============================================================================

compose() {
    if docker compose version &> /dev/null; then
        docker compose "$@"
    else
        docker-compose "$@"
    fi
}

# =============================================================================
# Commands
# =============================================================================

cmd_build() {
    header "Building Docker Image"
    run_checks
    
    info "Building image..."
    compose build
    
    success "Build complete"
}

cmd_rebuild() {
    header "Rebuilding Docker Image (no cache)"
    run_checks
    
    info "Rebuilding image with --no-cache..."
    compose build --no-cache
    
    success "Rebuild complete"
}

cmd_start() {
    header "Starting Services"
    run_checks
    check_env_file || true
    
    info "Starting containers..."
    compose up -d
    
    success "Services started"
    cmd_status
}

cmd_stop() {
    header "Stopping Services"
    
    info "Stopping containers..."
    compose down
    
    success "Services stopped"
}

cmd_restart() {
    header "Restarting Services"
    
    cmd_stop
    cmd_start
}

cmd_status() {
    header "Container Status"
    
    compose ps -a
    
    echo ""
    info "Resource usage:"
    docker stats --no-stream --format "table {{.Name}}\t{{.CPUPerc}}\t{{.MemUsage}}\t{{.NetIO}}" $(compose ps -q 2>/dev/null) 2>/dev/null || true
}

cmd_logs() {
    header "Container Logs (last 100 lines)"
    
    compose logs --tail=100
}

cmd_logs_follow() {
    header "Following Container Logs"
    info "Press Ctrl+C to stop following logs"
    echo ""
    
    compose logs -f --tail=50
}

cmd_verify() {
    header "Running Health Checks"
    
    info "Checking if container is running..."
    if ! compose ps | grep -q "Up"; then
        error "Container is not running"
        return 1
    fi
    success "Container is running"
    
    info "Waiting for API to be ready..."
    local retries=0
    while [[ $retries -lt $HEALTH_CHECK_RETRIES ]]; do
        if curl -s -f "$HEALTH_CHECK_URL" > /dev/null 2>&1; then
            success "API is healthy and responding"
            
            # Show API info
            info "API Response:"
            curl -s "$HEALTH_CHECK_URL" | python3 -m json.tool 2>/dev/null || curl -s "$HEALTH_CHECK_URL"
            echo ""
            return 0
        fi
        
        retries=$((retries + 1))
        echo -ne "\r${BLUE}[INFO]${NC} Waiting for API... ($retries/$HEALTH_CHECK_RETRIES)"
        sleep $HEALTH_CHECK_DELAY
    done
    
    echo ""
    error "API health check failed after $HEALTH_CHECK_RETRIES attempts"
    info "Check logs with: ./deploy.sh logs"
    return 1
}

cmd_shell() {
    header "Opening Shell in Container"
    
    info "Connecting to container..."
    compose exec $SERVICE_NAME /bin/sh || compose exec $SERVICE_NAME /bin/bash
}

cmd_cleanup() {
    header "Cleaning Up Docker Resources"
    
    warning "This will remove:"
    echo "  - All project containers"
    echo "  - All project images"
    echo "  - Unused Docker resources (dangling images, networks)"
    echo ""
    read -p "Are you sure? (y/N) " -n 1 -r
    echo ""
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        info "Stopping containers..."
        compose down --rmi local -v 2>/dev/null || true
        
        info "Removing project images..."
        docker images | grep "$PROJECT_NAME" | awk '{print $3}' | xargs -r docker rmi -f 2>/dev/null || true
        
        info "Pruning unused resources..."
        docker system prune -f
        
        success "Cleanup complete"
    else
        info "Cleanup cancelled"
    fi
}

cmd_deploy() {
    header "Full Deployment"
    run_checks
    
    if ! check_env_file; then
        error "Please configure .env file before deploying"
        exit 1
    fi
    
    info "Stopping existing containers..."
    compose down 2>/dev/null || true
    
    info "Building image..."
    compose build
    
    info "Starting services..."
    compose up -d
    
    info "Running health checks..."
    sleep 3
    if cmd_verify; then
        success "Deployment complete!"
        echo ""
        info "Access the application at: http://localhost:8000"
        info "E-Paper reader at: http://localhost:8000/reader/"
    else
        error "Deployment completed but health check failed"
        info "Check logs with: ./deploy.sh logs"
        exit 1
    fi
}

cmd_clean_deploy() {
    header "Clean Deployment"
    warning "This will remove all existing containers and images before deploying"
    echo ""
    read -p "Continue? (y/N) " -n 1 -r
    echo ""
    
    if [[ $REPLY =~ ^[Yy]$ ]]; then
        info "Removing existing containers and images..."
        compose down --rmi local -v 2>/dev/null || true
        
        cmd_deploy
    else
        info "Clean deploy cancelled"
    fi
}

cmd_help() {
    echo ""
    echo -e "${CYAN}PatreonReader Docker Deployment Script${NC}"
    echo ""
    echo "Usage: ./deploy.sh [command]"
    echo ""
    echo "Commands:"
    echo "  deploy       Full deployment (stop, rebuild, verify, start) [default]"
    echo "  build        Incremental build only"
    echo "  rebuild      Force rebuild with --no-cache"
    echo "  clean-deploy Full cleanup including images, then fresh deploy"
    echo "  start        Start services"
    echo "  stop         Stop services"
    echo "  restart      Restart services"
    echo "  status       Show container status and resource usage"
    echo "  logs         View logs (last 100 lines)"
    echo "  logs-follow  Follow logs in real-time (Ctrl+C to stop)"
    echo "  verify       Run health checks"
    echo "  shell        Open shell in running container"
    echo "  cleanup      Remove containers, images, prune resources"
    echo "  help         Show this help message"
    echo ""
    echo "Examples:"
    echo "  ./deploy.sh              # Run full deployment"
    echo "  ./deploy.sh start        # Start services"
    echo "  ./deploy.sh logs-follow  # Follow logs"
    echo "  ./deploy.sh status       # Check container status"
    echo ""
    echo "Configuration:"
    echo "  Edit .env file to configure:"
    echo "    - API_TOKEN: Authentication token for API access"
    echo "    - PATREON_SESSION_ID: Your Patreon session cookie"
    echo "    - SYNC_INTERVAL_HOURS: Auto-sync interval (default: 2)"
    echo ""
}

# =============================================================================
# Main Entry Point
# =============================================================================

# Change to script directory
cd "$(dirname "$0")"

# Parse command
COMMAND="${1:-deploy}"

case "$COMMAND" in
    deploy)
        cmd_deploy
        ;;
    build)
        cmd_build
        ;;
    rebuild)
        cmd_rebuild
        ;;
    clean-deploy)
        cmd_clean_deploy
        ;;
    start)
        cmd_start
        ;;
    stop)
        cmd_stop
        ;;
    restart)
        cmd_restart
        ;;
    status)
        cmd_status
        ;;
    logs)
        cmd_logs
        ;;
    logs-follow|logs-f)
        cmd_logs_follow
        ;;
    verify|health)
        cmd_verify
        ;;
    shell|sh|bash)
        cmd_shell
        ;;
    cleanup|clean)
        cmd_cleanup
        ;;
    help|-h|--help)
        cmd_help
        ;;
    *)
        error "Unknown command: $COMMAND"
        cmd_help
        exit 1
        ;;
esac
