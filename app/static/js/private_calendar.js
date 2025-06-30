class CalendarApp {
    constructor() {
        this.currentDate = new Date();
        this.currentView = 'month';
        this.events = [];
        this.selectedEvent = null;
        this.isLoading = false;
        
        this.init();
    }

    init() {
        this.renderCalendar();
        this.updateCurrentDate();
        this.showLoader();
        this.bindEvents();
        this.loadEvents();
        this.autoRefresh();
    }

    bindEvents() {
        document.getElementById('prev-btn').addEventListener('click', () => this.navigatePrevious());
        document.getElementById('next-btn').addEventListener('click', () => this.navigateNext());
        document.getElementById('today-btn').addEventListener('click', () => this.goToToday());

        document.querySelectorAll('.view-btn').forEach(btn => {
            btn.addEventListener('click', (e) => this.switchView(e.target.dataset.view));
        });

        document.getElementById('add-event-btn').addEventListener('click', () => this.openEventModal());
        document.getElementById('close-modal').addEventListener('click', () => this.closeEventModal());
        document.getElementById('close-settings').addEventListener('click', () => this.closeSettingsModal());
        document.getElementById('settings-btn').addEventListener('click', () => this.openSettingsModal());

        document.getElementById('event-form').addEventListener('submit', (e) => this.handleEventSubmit(e));
        document.getElementById('cancel-btn').addEventListener('click', () => this.closeEventModal());
        document.getElementById('delete-btn').addEventListener('click', () => this.deleteEvent());

        document.getElementById('menu-toggle').addEventListener('click', () => this.toggleSidePanel());
        document.getElementById('all-day').addEventListener('change', (e) => this.toggleAllDay(e.target.checked));

        document.getElementById('event-modal').addEventListener('click', (e) => {
            if (e.target.id === 'event-modal') this.closeEventModal();
        });
        document.getElementById('settings-modal').addEventListener('click', (e) => {
            if (e.target.id === 'settings-modal') this.closeSettingsModal();
        });
    }

    async loadEvents() {
        try {
            this.isLoading = true;
            this.showLoader();
            
            const response = await fetch('/api/events');
            if (response.ok) {
                const data = await response.json();
                this.events = data.events || this.getDefaultEvents();
            } else {
                this.events = this.getDefaultEvents();
            }
        } catch (error) {
            console.error('Failed to load events:', error);
            this.events = this.getDefaultEvents();
        } finally {
            this.isLoading = false;
            this.hideLoader();
            this.renderCalendar();
        }
    }

    getDefaultEvents() {
        return [
            {
                id: 1,
                title: 'Team Meeting',
                start_date: '2025-01-15T10:00:00',
                end_date: '2025-01-15T11:00:00',
                description: 'Weekly team sync',
                color: '#4285f4'
            },
            {
                id: 2,
                title: 'Project Review',
                start_date: '2025-01-20T14:00:00',
                end_date: '2025-01-20T15:30:00',
                description: 'Q1 project milestone review',
                color: '#34a853'
            },
            {
                id: 3,
                title: 'Lab Meeting',
                start_date: new Date().toISOString().split('T')[0] + 'T14:00:00',
                end_date: new Date().toISOString().split('T')[0] + 'T16:00:00',
                description: 'Monthly lab sync',
                color: '#ea4335'
            }
        ];
    }

    autoRefresh() {
        setInterval(() => {
            if (!this.isLoading) {
                this.loadEvents();
            }
        }, 300000);
    }

    showLoader() {
        if (!document.getElementById('calendar-loader')) {
            const loader = document.createElement('div');
            loader.id = 'calendar-loader';
            loader.innerHTML = `
                <div class="loader-backdrop">
                    <div class="loader-content">
                        <div class="spinner"></div>
                        <p>Loading calendar...</p>
                    </div>
                </div>
            `;
            document.body.appendChild(loader);
        }
        document.getElementById('calendar-loader').style.display = 'flex';
    }

    hideLoader() {
        const loader = document.getElementById('calendar-loader');
        if (loader) {
            loader.style.display = 'none';
        }
    }

    navigatePrevious() {
        if (this.currentView === 'month') {
            this.currentDate.setMonth(this.currentDate.getMonth() - 1);
        } else if (this.currentView === 'week') {
            this.currentDate.setDate(this.currentDate.getDate() - 7);
        } else if (this.currentView === 'day') {
            this.currentDate.setDate(this.currentDate.getDate() - 1);
        }
        this.updateCurrentDate();
        this.renderCalendar();
    }

    navigateNext() {
        if (this.currentView === 'month') {
            this.currentDate.setMonth(this.currentDate.getMonth() + 1);
        } else if (this.currentView === 'week') {
            this.currentDate.setDate(this.currentDate.getDate() + 7);
        } else if (this.currentView === 'day') {
            this.currentDate.setDate(this.currentDate.getDate() + 1);
        }
        this.updateCurrentDate();
        this.renderCalendar();
    }

    goToToday() {
        this.currentDate = new Date();
        this.updateCurrentDate();
        this.renderCalendar();
    }

    switchView(view) {
        this.currentView = view;
        document.querySelectorAll('.view-btn').forEach(btn => btn.classList.remove('active'));
        document.querySelector(`[data-view="${view}"]`).classList.add('active');
        this.updateCurrentDate();
        this.renderCalendar();
    }

    updateCurrentDate() {
        const dateElement = document.getElementById('current-date');
        const options = { year: 'numeric', month: 'long' };
        
        if (this.currentView === 'month') {
            dateElement.textContent = this.currentDate.toLocaleDateString('en-US', options);
        } else if (this.currentView === 'week') {
            const weekStart = this.getWeekStart(this.currentDate);
            const weekEnd = new Date(weekStart);
            weekEnd.setDate(weekEnd.getDate() + 6);
            dateElement.textContent = `${weekStart.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} - ${weekEnd.toLocaleDateString('en-US', { month: 'short', day: 'numeric', year: 'numeric' })}`;
        } else if (this.currentView === 'day') {
            dateElement.textContent = this.currentDate.toLocaleDateString('en-US', { 
                weekday: 'long', 
                year: 'numeric', 
                month: 'long', 
                day: 'numeric' 
            });
        }
    }

    renderCalendar() {
        const content = document.getElementById('calendar-content');
        content.innerHTML = '';

        if (this.currentView === 'month') {
            this.renderMonthView(content);
        } else if (this.currentView === 'week') {
            this.renderWeekView(content);
        } else if (this.currentView === 'day') {
            this.renderDayView(content);
        }
    }

    renderMonthView(container) {
        const firstDay = new Date(this.currentDate.getFullYear(), this.currentDate.getMonth(), 1);
        const startDate = this.getWeekStart(firstDay);
        
        const currentDate = new Date(startDate);
        for (let i = 0; i < 42; i++) {
            const cell = this.createCalendarCell(currentDate);
            container.appendChild(cell);
            currentDate.setDate(currentDate.getDate() + 1);
        }
    }

    renderWeekView(container) {
        container.style.gridTemplateColumns = 'repeat(7, 1fr)';
        const weekStart = this.getWeekStart(this.currentDate);
        
        for (let i = 0; i < 7; i++) {
            const dayDate = new Date(weekStart);
            dayDate.setDate(dayDate.getDate() + i);
            const cell = this.createWeekDayCell(dayDate);
            container.appendChild(cell);
        }
    }

    renderDayView(container) {
        container.style.gridTemplateColumns = '1fr';
        const cell = this.createDayCell(this.currentDate);
        container.appendChild(cell);
    }

    createCalendarCell(date) {
        const cell = document.createElement('div');
        cell.className = 'calendar-cell';
        
        const today = new Date();
        const isToday = this.isSameDay(date, today);
        const isCurrentMonth = date.getMonth() === this.currentDate.getMonth();
        
        if (isToday) cell.classList.add('today');
        if (!isCurrentMonth) cell.classList.add('other-month');

        const dateElement = document.createElement('div');
        dateElement.className = 'calendar-date';
        dateElement.textContent = date.getDate();
        cell.appendChild(dateElement);

        const eventsContainer = document.createElement('div');
        eventsContainer.className = 'calendar-events';
        
        const dayEvents = this.getEventsForDate(date);
        dayEvents.forEach(event => {
            const eventElement = document.createElement('div');
            eventElement.className = 'calendar-event';
            eventElement.textContent = event.title;
            eventElement.style.backgroundColor = event.color;
            eventElement.addEventListener('click', (e) => {
                e.stopPropagation();
                this.editEvent(event);
            });
            eventsContainer.appendChild(eventElement);
        });
        
        cell.appendChild(eventsContainer);
        cell.addEventListener('click', () => this.openEventModal(date));

        return cell;
    }

    createWeekDayCell(date) {
        const cell = document.createElement('div');
        cell.className = 'calendar-cell week-cell';
        cell.style.minHeight = '400px';
        
        const today = new Date();
        const isToday = this.isSameDay(date, today);
        
        if (isToday) cell.classList.add('today');

        const header = document.createElement('div');
        header.className = 'week-day-header';
        header.innerHTML = `
            <div class="week-day-name">${date.toLocaleDateString('en-US', { weekday: 'short' })}</div>
            <div class="week-day-number">${date.getDate()}</div>
        `;
        cell.appendChild(header);

        const eventsContainer = document.createElement('div');
        eventsContainer.className = 'calendar-events';
        
        const dayEvents = this.getEventsForDate(date);
        dayEvents.forEach(event => {
            const eventElement = document.createElement('div');
            eventElement.className = 'calendar-event week-event';
            eventElement.innerHTML = `
                <div class="event-time">${this.formatTime(new Date(event.start_date))}</div>
                <div class="event-title">${event.title}</div>
            `;
            eventElement.style.backgroundColor = event.color;
            eventElement.addEventListener('click', (e) => {
                e.stopPropagation();
                this.editEvent(event);
            });
            eventsContainer.appendChild(eventElement);
        });
        
        cell.appendChild(eventsContainer);
        cell.addEventListener('click', () => this.openEventModal(date));

        return cell;
    }

    createDayCell(date) {
        const cell = document.createElement('div');
        cell.className = 'calendar-cell day-cell';
        cell.style.minHeight = '600px';
        cell.style.padding = '20px';
        
        const header = document.createElement('div');
        header.className = 'day-header';
        header.innerHTML = `
            <h3>${date.toLocaleDateString('en-US', { weekday: 'long', month: 'long', day: 'numeric' })}</h3>
        `;
        cell.appendChild(header);

        const eventsContainer = document.createElement('div');
        eventsContainer.className = 'day-events';
        
        const dayEvents = this.getEventsForDate(date);
        dayEvents.forEach(event => {
            const eventElement = document.createElement('div');
            eventElement.className = 'day-event';
            eventElement.innerHTML = `
                <div class="event-time">${this.formatTime(new Date(event.start_date))} - ${this.formatTime(new Date(event.end_date))}</div>
                <div class="event-title">${event.title}</div>
                <div class="event-description">${event.description || ''}</div>
            `;
            eventElement.style.borderLeft = `4px solid ${event.color}`;
            eventElement.addEventListener('click', () => this.editEvent(event));
            eventsContainer.appendChild(eventElement);
        });
        
        cell.appendChild(eventsContainer);
        cell.addEventListener('click', () => this.openEventModal(date));

        return cell;
    }

    getWeekStart(date) {
        const start = new Date(date);
        start.setDate(start.getDate() - start.getDay());
        return start;
    }

    isSameDay(date1, date2) {
        return date1.getDate() === date2.getDate() &&
               date1.getMonth() === date2.getMonth() &&
               date1.getFullYear() === date2.getFullYear();
    }

    getEventsForDate(date) {
        return this.events.filter(event => {
            const eventDate = new Date(event.start_date);
            return this.isSameDay(eventDate, date);
        });
    }

    formatTime(date) {
        return date.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit', hour12: true });
    }

    openEventModal(date = null) {
        const modal = document.getElementById('event-modal');
        const form = document.getElementById('event-form');
        
        this.selectedEvent = null;
        form.reset();
        
        document.getElementById('modal-title').textContent = 'Add Event';
        document.getElementById('delete-btn').style.display = 'none';
        
        if (date) {
            const startDate = new Date(date);
            const endDate = new Date(date);
            endDate.setHours(endDate.getHours() + 1);
            
            document.getElementById('event-date').value = this.formatDateForInput(startDate);
            document.getElementById('event-start-time').value = this.formatTimeForInput(startDate);
            document.getElementById('event-end-time').value = this.formatTimeForInput(endDate);
        }
        
        modal.style.display = 'flex';
    }

    editEvent(event) {
        const modal = document.getElementById('event-modal');
        
        this.selectedEvent = event;
        
        document.getElementById('modal-title').textContent = 'Edit Event';
        document.getElementById('delete-btn').style.display = 'inline-block';
        
        const startDate = new Date(event.start_date);
        const endDate = new Date(event.end_date);
        
        document.getElementById('event-title').value = event.title;
        document.getElementById('event-description').value = event.description || '';
        document.getElementById('event-date').value = this.formatDateForInput(startDate);
        document.getElementById('event-start-time').value = this.formatTimeForInput(startDate);
        document.getElementById('event-end-time').value = this.formatTimeForInput(endDate);
        
        modal.style.display = 'flex';
    }

    closeEventModal() {
        document.getElementById('event-modal').style.display = 'none';
        this.selectedEvent = null;
    }

    openSettingsModal() {
        document.getElementById('settings-modal').style.display = 'flex';
    }

    closeSettingsModal() {
        document.getElementById('settings-modal').style.display = 'none';
    }

    async handleEventSubmit(e) {
        e.preventDefault();
        
        const eventData = {
            title: document.getElementById('event-title').value,
            description: document.getElementById('event-description').value,
            start_date: this.combineDateTimeForSave(
                document.getElementById('event-date').value,
                document.getElementById('event-start-time').value
            ),
            end_date: this.combineDateTimeForSave(
                document.getElementById('event-date').value,
                document.getElementById('event-end-time').value
            ),
            color: '#4285f4'
        };

        try {
            this.showLoader();
            
            if (this.selectedEvent) {
                eventData.id = this.selectedEvent.id;
                const response = await fetch(`/api/events/${this.selectedEvent.id}`, {
                    method: 'PUT',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(eventData)
                });
                
                if (response.ok) {
                    const index = this.events.findIndex(e => e.id === this.selectedEvent.id);
                    if (index !== -1) {
                        this.events[index] = eventData;
                    }
                }
            } else {
                const response = await fetch('/api/events', {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: JSON.stringify(eventData)
                });
                
                if (response.ok) {
                    const result = await response.json();
                    eventData.id = result.id || Date.now();
                    this.events.push(eventData);
                } else {
                    eventData.id = Date.now();
                    this.events.push(eventData);
                }
            }
        } catch (error) {
            console.error('Failed to save event:', error);
            if (!this.selectedEvent) {
                eventData.id = Date.now();
                this.events.push(eventData);
            }
        } finally {
            this.hideLoader();
            this.renderCalendar();
            this.closeEventModal();
        }
    }

    async deleteEvent() {
        if (!this.selectedEvent) return;
        
        if (confirm('Are you sure you want to delete this event?')) {
            try {
                this.showLoader();
                
                await fetch(`/api/events/${this.selectedEvent.id}`, {
                    method: 'DELETE'
                });
                
                this.events = this.events.filter(e => e.id !== this.selectedEvent.id);
            } catch (error) {
                console.error('Failed to delete event:', error);
                this.events = this.events.filter(e => e.id !== this.selectedEvent.id);
            } finally {
                this.hideLoader();
                this.renderCalendar();
                this.closeEventModal();
            }
        }
    }

    toggleSidePanel() {
        const sidePanel = document.getElementById('side-panel');
        const calendarMain = document.querySelector('.calendar-main');
        
        if (sidePanel.style.display === 'none') {
            sidePanel.style.display = 'block';
            calendarMain.style.gridTemplateColumns = '300px 1fr';
        } else {
            sidePanel.style.display = 'none';
            calendarMain.style.gridTemplateColumns = '1fr';
        }
    }

    toggleAllDay(isAllDay) {
        const startTime = document.getElementById('event-start-time');
        const endTime = document.getElementById('event-end-time');
        
        if (isAllDay) {
            startTime.style.display = 'none';
            endTime.style.display = 'none';
        } else {
            startTime.style.display = 'block';
            endTime.style.display = 'block';
        }
    }

    formatDateForInput(date) {
        return date.toISOString().split('T')[0];
    }

    formatTimeForInput(date) {
        return date.toTimeString().slice(0, 5);
    }

    combineDateTimeForSave(date, time) {
        if (!time) time = '00:00';
        return `${date}T${time}:00`;
    }
}

document.addEventListener('DOMContentLoaded', () => {
    const calendarApp = new CalendarApp();
    
    document.addEventListener('visibilitychange', () => {
        if (!document.hidden && !calendarApp.isLoading) {
            calendarApp.loadEvents();
        }
    });
    
    window.addEventListener('focus', () => {
        if (!calendarApp.isLoading) {
            calendarApp.loadEvents();
        }
    });
});