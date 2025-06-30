document.addEventListener('DOMContentLoaded', function() {
    // Initialize weather status
    updateWeatherStatus();
    
    // Set up auto-refresh for certain elements
    setInterval(updateWeatherStatus, 300000); // Update every 5 minutes
});

function updateWeatherStatus() {
    // Simulate weather data update
    const weatherElement = document.getElementById('weatherStatus');
    if (weatherElement) {
        // In real implementation, this would fetch actual weather data
        const conditions = ['Clear', 'Cloudy', 'Rainy', 'Windy'];
        const randomCondition = conditions[Math.floor(Math.random() * conditions.length)];
        weatherElement.textContent = randomCondition;
        
        // Update badge color based on condition
        weatherElement.className = 'card-badge';
        if (randomCondition === 'Clear') {
            weatherElement.style.background = '#48bb78';
        } else if (randomCondition === 'Cloudy') {
            weatherElement.style.background = '#ed8936';
        } else {
            weatherElement.style.background = '#e53e3e';
        }
    }
}

// Add smooth scroll behavior for internal links
document.querySelectorAll('a[href^="#"]').forEach(anchor => {
    anchor.addEventListener('click', function (e) {
        e.preventDefault();
        const target = document.querySelector(this.getAttribute('href'));
        if (target) {
            target.scrollIntoView({
                behavior: 'smooth',
                block: 'start'
            });
        }
    });
});

// Add hover effects and animations
document.querySelectorAll('.access-card').forEach(card => {
    card.addEventListener('mouseenter', function() {
        this.style.transform = 'translateY(-5px)';
    });
    
    card.addEventListener('mouseleave', function() {
        this.style.transform = 'translateY(0)';
    });
});