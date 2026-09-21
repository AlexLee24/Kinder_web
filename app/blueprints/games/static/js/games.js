let secret = "";
let attempts = 0;

function generateSecret() {
    let digits = ["0", "1", "2", "3", "4", "5", "6", "7", "8", "9"];
    secret = "";
    for (let i = 0; i < 4; i++) {
        let idx = Math.floor(Math.random() * digits.length);
        secret += digits[idx];
        digits.splice(idx, 1);
    }
    console.log("Debug mode: secret is", secret);
}

function initGame() {
    generateSecret();
    attempts = 0;
    document.getElementById("history-body").innerHTML = "";
    document.getElementById("guess-input").value = "";
    document.getElementById("guess-input").disabled = false;
    document.getElementById("btn-guess").disabled = false;
    document.getElementById("guess-input").focus();
    updateStatus("Game Restarted! Guessed 4 new unique digits.", "#4db8ff");
}

function updateStatus(message, color = "#fff") {
    const el = document.getElementById("game-status");
    el.innerText = message;
    el.style.color = color;
}

function handleKeyPress(e) {
    if (e.key === "Enter") {
        makeGuess();
    }
}

function makeGuess() {
    const inputEl = document.getElementById("guess-input");
    const guess = inputEl.value.trim();

    // Validation
    if (guess.length !== 4) {
        updateStatus("Please enter exactly 4 digits.", "#ff4757");
        return;
    }
    if (!/^\d+$/.test(guess)) {
        updateStatus("Numbers only!", "#ff4757");
        return;
    }
    const uniqueDigits = new Set(guess.split(""));
    if (uniqueDigits.size !== 4) {
        updateStatus("Digits must be unique!", "#ff4757");
        return;
    }

    attempts++;
    
    // Calculate A and B
    let A = 0;
    let B = 0;
    for (let i = 0; i < 4; i++) {
        if (guess[i] === secret[i]) {
            A++;
        } else if (secret.includes(guess[i])) {
            B++;
        }
    }

    // Add to history table
    const tbody = document.getElementById("history-body");
    const tr = document.createElement("tr");
    tr.innerHTML = `
        <td>${attempts}</td>
        <td style="letter-spacing: 2px;">${guess}</td>
        <td><span class="result-a">${A}A</span><span class="result-b">${B}B</span></td>
    `;
    tbody.insertBefore(tr, tbody.firstChild);

    // End game logic
    if (A === 4) {
        updateStatus(`Congratulations! You found the number in ${attempts} attempts!`, "#4CAF50");
        document.getElementById("btn-guess").disabled = true;
        document.getElementById("guess-input").disabled = true;
        submitScore(attempts);
    } else {
        updateStatus("Keep trying...", "#fff");
    }
    
    inputEl.value = "";
    if (A !== 4) {
        inputEl.focus();
    }
}

function submitScore(attempts) {
    fetch('/api/games/leaderboard', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ attempts: attempts })
    })
    .then(r => r.json())
    .then(data => {
        if (data.success) {
            loadLeaderboard();
        }
    })
    .catch(e => console.error("Error submitting score:", e));
}

function loadLeaderboard() {
    fetch('/api/games/leaderboard')
        .then(r => r.json())
        .then(data => {
            const tbody = document.getElementById("leaderboard-body");
            tbody.innerHTML = "";
            
            if (data.length === 0) {
                tbody.innerHTML = '<tr><td colspan="3" style="color: #aaa;">No runs yet. Be the first!</td></tr>';
                return;
            }
            
            data.forEach((run, index) => {
                const tr = document.createElement("tr");
                // Rank formatting
                let rankText = `${index + 1}`;
                if (index === 0) rankText = "🥇 " + rankText;
                else if (index === 1) rankText = "🥈 " + rankText;
                else if (index === 2) rankText = "🥉 " + rankText;
                
                tr.innerHTML = `
                    <td style="color: #C5A059; font-weight: bold;">${rankText}</td>
                    <td style="text-align: left;">${run.name}</td>
                    <td style="color: #4db8ff; font-weight: bold;">${run.attempts}</td>
                `;
                tbody.appendChild(tr);
            });
        })
        .catch(e => {
            console.error("Error loading leaderboard:", e);
            document.getElementById("leaderboard-body").innerHTML = '<tr><td colspan="3" style="color: #ff4757;">Failed to load data</td></tr>';
        });
}

// Start immediately loading
document.addEventListener("DOMContentLoaded", () => {
    initGame();
    loadLeaderboard();
});
