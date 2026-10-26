/**
 * Smart Attendance System - Live Attendance Session Controller
 * Handles webcam capture, frame dispatching to recognition endpoint,
 * real-time attendance HUD feedback, duplicate rejection, and manual override.
 */

(function () {
    const config = window.SESSION_CONFIG || {};
    const sessionId = config.sessionId;

    // DOM Elements
    const video = document.getElementById('sessionVideo');
    const canvas = document.getElementById('sessionCanvas');
    const startCamBtn = document.getElementById('startCamBtn');
    const scanSingleBtn = document.getElementById('captureSingleFrameBtn');
    const toggleScanModeBtn = document.getElementById('toggleScanModeBtn');
    const scanModeLabel = document.getElementById('scanModeLabel');
    const endSessionBtn = document.getElementById('endSessionBtn');

    // HUD Elements
    const statusPill = document.getElementById('recognitionStatusPill');
    const statusText = document.getElementById('recognitionStatusText');
    const feedbackIcon = document.getElementById('feedbackIcon');
    const feedbackTitle = document.getElementById('feedbackTitle');
    const feedbackDetails = document.getElementById('feedbackDetails');
    const cameraBadge = document.getElementById('cameraStatusBadge');
    const scanCounterDisplay = document.getElementById('scanCounter');
    const laserLine = document.getElementById('scanLaserLine');
    const hudNotice = document.getElementById('hudNotice');
    const timerDisplay = document.getElementById('sessionTimer');

    // Metrics & Table
    const presentDisplay = document.getElementById('presentCount');
    const enrolledDisplay = document.getElementById('enrolledCount');
    const percentageDisplay = document.getElementById('percentageDisplay');
    const progressBar = document.getElementById('attendanceProgressBar');
    const progressLabel = document.getElementById('progressBarLabel');
    const attendanceTableBody = document.getElementById('sessionAttendanceBody');
    const emptyRow = document.getElementById('emptyAttendanceRow');

    // Manual Override
    const manualSelect = document.getElementById('manualStudentSelect');
    const manualBtn = document.getElementById('markManualBtn');

    // State Variables
    let mediaStream = null;
    let isAutoScanning = false;
    let autoScanInterval = null;
    let isProcessingFrame = false;
    let scanCount = 0;
    let presentStudentIds = new Set();
    let currentPresentCount = config.presentCount || 0;
    const totalEnrolled = config.totalEnrolled || 1;

    // Collect pre-existing marked student IDs from table
    document.querySelectorAll('.attendance-feed-row').forEach(row => {
        const sid = row.id.replace('row-', '');
        if (sid) presentStudentIds.add(String(sid));
    });

    // 1. Session Duration Timer
    let sessionSeconds = 0;
    setInterval(() => {
        sessionSeconds++;
        const hrs = String(Math.floor(sessionSeconds / 3600)).padStart(2, '0');
        const mins = String(Math.floor((sessionSeconds % 3600) / 60)).padStart(2, '0');
        const secs = String(sessionSeconds % 60).padStart(2, '0');
        if (timerDisplay) timerDisplay.textContent = `${hrs}:${mins}:${secs}`;
    }, 1000);

    // 2. Camera Initialization
    async function startCamera() {
        try {
            mediaStream = await navigator.mediaDevices.getUserMedia({
                video: { width: { ideal: 640 }, height: { ideal: 480 }, facingMode: 'user' }
            });
            video.srcObject = mediaStream;
            
            cameraBadge.innerHTML = '<i class="bi bi-circle-fill text-success me-1"></i> CAMERA ACTIVE';
            hudNotice.style.display = 'none';
            startCamBtn.disabled = true;
            scanSingleBtn.disabled = false;
            
            showToast('Webcam feed linked successfully', 'info');
        } catch (err) {
            console.error('Camera initialization error:', err);
            cameraBadge.innerHTML = '<i class="bi bi-x-circle text-danger me-1"></i> CAMERA BLOCKED';
            feedbackTitle.textContent = 'Camera Unavailable';
            feedbackDetails.textContent = 'Please permit webcam access or attach a video device. (' + err.message + ')';
            showToast('Camera error: ' + err.message, 'danger');
        }
    }

    // 3. Capture Frame and Send to Backend Recognition API
    async function processCurrentFrame() {
        if (!mediaStream || isProcessingFrame || !video.videoWidth) return;

        isProcessingFrame = true;
        scanCount++;
        scanCounterDisplay.textContent = `${scanCount} SCANS`;

        // Render to hidden canvas
        canvas.width = video.videoWidth || 640;
        canvas.height = video.videoHeight || 480;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
        const base64Image = canvas.toDataURL('image/jpeg', 0.85);

        // Flash HUD laser
        laserLine.style.display = 'block';

        try {
            const result = await fetchJson(`/api/sessions/${sessionId}/recognize`, {
                method: 'POST',
                body: JSON.stringify({ image: base64Image })
            });

            handleRecognitionResult(result);
        } catch (err) {
            console.error('Recognition error:', err);
            setHudStatus('danger', 'bi-exclamation-triangle-fill text-danger', 'Service Error', err.message);
        } finally {
            isProcessingFrame = false;
            setTimeout(() => {
                if (!isAutoScanning) laserLine.style.display = 'none';
            }, 300);
        }
    }

    // 4. Handle Recognition Server Response
    function handleRecognitionResult(res) {
        const status = res.status; // 'marked', 'already_marked', 'not_enrolled', 'unrecognized', 'no_face'
        const student = res.student || {};

        if (status === 'marked' || status === 'success') {
            setHudStatus(
                'success',
                'bi-check-circle-fill text-success',
                `Verified: ${student.name}`,
                `Roll No: ${student.roll_no} | Marked at ${res.timestamp || new Date().toLocaleTimeString()} (Face ID)`
            );
            showToast(`Attendance marked for ${student.name} (${student.roll_no})`, 'success');

            // Add record row to table
            addAttendanceRow({
                student_id: student.id,
                roll_no: student.roll_no,
                student_name: student.name,
                timestamp: res.timestamp || new Date().toLocaleTimeString(),
                method: 'Face Recognition'
            });

            updateAttendanceMetrics();
        } 
        else if (status === 'already_marked') {
            setHudStatus(
                'warning',
                'bi-exclamation-circle-fill text-warning',
                `Already Marked: ${student.name}`,
                `${student.roll_no} was already recorded for this session. Duplicate rejected.`
            );
        } 
        else if (status === 'not_enrolled') {
            setHudStatus(
                'warning',
                'bi-person-x-fill text-warning',
                `Not Enrolled: ${student.name}`,
                `${student.roll_no} is registered in the system but not enrolled in this specific course roster.`
            );
        } 
        else if (status === 'unrecognized' || status === 'unknown') {
            setHudStatus(
                'danger',
                'bi-question-circle-fill text-danger',
                'Unrecognized Face',
                'Face detected in camera viewport, but does not match any registered student embeddings.'
            );
        }
        else if (status === 'no_face') {
            setHudStatus(
                'idle',
                'bi-person-bounding-box text-muted',
                'Searching for Face...',
                'Position face inside center guidelines with adequate lighting.'
            );
        }
    }

    // Set HUD Status Pill and Feedback Card
    function setHudStatus(type, iconClass, title, details) {
        statusPill.className = `recognition-status-pill ${type}`;
        statusText.textContent = title;

        feedbackIcon.className = `bi ${iconClass}`;
        feedbackTitle.textContent = title;
        feedbackDetails.textContent = details;
    }

    // Add Attendance Row into Table with animation
    function addAttendanceRow(record) {
        if (presentStudentIds.has(String(record.student_id))) return;
        presentStudentIds.add(String(record.student_id));

        if (emptyRow) emptyRow.remove();

        const tr = document.createElement('tr');
        tr.className = 'attendance-feed-row';
        tr.id = `row-${record.student_id}`;
        tr.innerHTML = `
            <td>
                <span class="badge bg-dark-card text-primary border border-primary-subtle font-monospace px-2 py-1 fs-xs">
                    ${record.roll_no}
                </span>
            </td>
            <td class="fw-semibold text-white fs-sm">${record.student_name}</td>
            <td class="text-muted fs-xs">${record.timestamp}</td>
            <td>
                <span class="badge badge-soft-primary rounded-pill px-2 py-1 fs-xxs">
                    <i class="bi bi-camera-fill me-1"></i> ${record.method}
                </span>
            </td>
            <td>
                <span class="badge badge-soft-success rounded-pill px-2 py-1 fs-xs">
                    <i class="bi bi-check-circle-fill me-1"></i> Present
                </span>
            </td>
        `;

        attendanceTableBody.insertBefore(tr, attendanceTableBody.firstChild);
    }

    // Update Live Attendance Counters & Progress Bar
    function updateAttendanceMetrics() {
        currentPresentCount = presentStudentIds.size;
        presentDisplay.textContent = currentPresentCount;

        const percentage = totalEnrolled > 0 ? Math.round((currentPresentCount / totalEnrolled) * 100) : 0;
        percentageDisplay.textContent = `${percentage}%`;

        if (progressBar) {
            progressBar.style.width = `${percentage}%`;
            progressBar.setAttribute('aria-valuenow', percentage);
        }
        if (progressLabel) {
            progressLabel.textContent = `${currentPresentCount} of ${totalEnrolled} Students Present`;
        }
    }

    // 5. Auto-Scan Toggle
    function toggleAutoScan() {
        if (!mediaStream) {
            showToast('Please start camera first', 'warning');
            return;
        }

        if (isAutoScanning) {
            isAutoScanning = false;
            clearInterval(autoScanInterval);
            autoScanInterval = null;
            scanModeLabel.textContent = 'Start Auto-Scan';
            toggleScanModeBtn.className = 'btn btn-tech-outline rounded-pill px-3 fs-sm';
            laserLine.style.display = 'none';
            showToast('Auto-scan paused', 'info');
        } else {
            isAutoScanning = true;
            scanModeLabel.textContent = 'Pause Auto-Scan';
            toggleScanModeBtn.className = 'btn btn-outline-warning rounded-pill px-3 fs-sm';
            laserLine.style.display = 'block';
            showToast('Auto-scan active (scanning every 1.5s)', 'success');

            // Trigger immediate scan then interval
            processCurrentFrame();
            autoScanInterval = setInterval(processCurrentFrame, 1500);
        }
    }

    // 6. Manual Attendance Override
    async function handleManualAttendance() {
        const studentId = manualSelect?.value;
        if (!studentId) {
            showToast('Please select a student from the dropdown', 'warning');
            return;
        }

        manualBtn.disabled = true;
        manualBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Recording...';

        try {
            const resp = await fetchJson(`/api/sessions/${sessionId}/mark-manual`, {
                method: 'POST',
                body: JSON.stringify({ student_id: studentId })
            });

            handleRecognitionResult(resp);
            manualSelect.value = '';
        } catch (err) {
            showToast(err.message, 'danger');
        } finally {
            manualBtn.disabled = false;
            manualBtn.textContent = 'Mark Present';
        }
    }

    // 7. End Session Action
    async function endSession() {
        if (!confirm('Are you sure you want to conclude this attendance session?')) return;

        endSessionBtn.disabled = true;
        endSessionBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-1"></span> Closing Session...';

        try {
            await fetchJson(`/api/sessions/${sessionId}/end`, {
                method: 'POST'
            });

            showToast('Attendance session successfully completed', 'success');
            setTimeout(() => {
                window.location.href = `/reports?session_id=${sessionId}`;
            }, 800);
        } catch (err) {
            showToast('Failed to close session: ' + err.message, 'danger');
            endSessionBtn.disabled = false;
            endSessionBtn.innerHTML = '<i class="bi bi-stop-circle me-1"></i> Close Session';
        }
    }

    // Event Listeners
    startCamBtn?.addEventListener('click', startCamera);
    scanSingleBtn?.addEventListener('click', processCurrentFrame);
    toggleScanModeBtn?.addEventListener('click', toggleAutoScan);
    manualBtn?.addEventListener('click', handleManualAttendance);
    endSessionBtn?.addEventListener('click', endSession);

    // Clean up camera stream on page unload
    window.addEventListener('beforeunload', () => {
        if (mediaStream) {
            mediaStream.getTracks().forEach(track => track.stop());
        }
    });

})();
