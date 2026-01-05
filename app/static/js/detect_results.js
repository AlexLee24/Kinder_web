function toggleFlag(id, element) {
    const isActive = element.classList.contains('active');
    const newFlag = !isActive;
    
    // Add loading state
    element.style.opacity = '0.5';
    
    fetch('/api/toggle_flag', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            id: id,
            flag: newFlag
        })
    })
    .then(response => response.json())
    .then(data => {
        element.style.opacity = '1';
        if (data.success) {
            if (newFlag) {
                element.classList.add('active');
            } else {
                element.classList.remove('active');
            }
        } else {
            alert('Failed to update flag');
        }
    })
    .catch(error => {
        element.style.opacity = '1';
        console.error('Error:', error);
        alert('An error occurred');
    });
}

function changeDate(selectElement) {
    const date = selectElement.value;
    if (date) {
        window.location.href = `/detect?detect_results=${date}`;
    } else {
        window.location.href = '/detect';
    }
}

function setHost(matchId, targetName, redshift, source) {
    if (!confirm(`Are you sure you want to set this match as the host for ${targetName}? This will update the TNS redshift.`)) {
        return;
    }

    fetch('/api/set_host', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            match_id: matchId,
            target_name: targetName,
            redshift: redshift,
            source: source
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert('Host set successfully!');
            location.reload();
        } else {
            alert('Failed to set host: ' + (data.message || 'Unknown error'));
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('An error occurred');
    });
}

function unsetHost(targetName) {
    if (!confirm(`Are you sure you want to clear the host for ${targetName}?`)) {
        return;
    }

    fetch('/api/unset_host', {
        method: 'POST',
        headers: {
            'Content-Type': 'application/json',
        },
        body: JSON.stringify({
            target_name: targetName
        })
    })
    .then(response => response.json())
    .then(data => {
        if (data.success) {
            alert('Host cleared successfully!');
            location.reload();
        } else {
            alert('Failed to clear host: ' + (data.message || 'Unknown error'));
        }
    })
    .catch(error => {
        console.error('Error:', error);
        alert('An error occurred');
    });
}

// Back to Top Button
const backToTopBtn = document.getElementById("backToTopBtn");

if (backToTopBtn) {
    window.onscroll = function() {scrollFunction()};

    function scrollFunction() {
        if (document.body.scrollTop > 300 || document.documentElement.scrollTop > 300) {
            backToTopBtn.style.display = "block";
        } else {
            backToTopBtn.style.display = "none";
        }
    }

    backToTopBtn.addEventListener("click", function() {
        window.scrollTo({top: 0, behavior: 'smooth'});
    });
}


