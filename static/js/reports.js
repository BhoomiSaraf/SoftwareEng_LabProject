/**
 * Smart Attendance System - Reports & CSV Export Controller
 */

(function () {
    const courseFilter = document.getElementById('reportCourseFilter');
    const sectionFilter = document.getElementById('reportSectionFilter');
    const statusFilter = document.getElementById('reportStatusFilter');
    const searchInput = document.getElementById('reportSearchInput');
    const exportBtn = document.getElementById('exportCsvBtn');
    const reportRows = document.querySelectorAll('.report-row');

    // Summary Card Displays
    const summaryStudents = document.getElementById('summaryTotalStudents');
    const summaryEligible = document.getElementById('summaryEligibleCount');
    const summaryWarning = document.getElementById('summaryWarningCount');

    // Course and section are server-side filters (percentages depend on them); reload with the choice.
    function reloadWithScope() {
        const params = new URLSearchParams();
        if (courseFilter && courseFilter.value !== 'all') params.set('course_id', courseFilter.value);
        if (sectionFilter && sectionFilter.value !== 'all') params.set('section', sectionFilter.value);
        const qs = params.toString();
        window.location.href = '/reports' + (qs ? '?' + qs : '');
    }

    // Status and text search only narrow the rows already on the page.
    function applyFilters() {
        const selectedStatus = statusFilter?.value || 'all';
        const q = (searchInput?.value || '').toLowerCase().trim();

        let visibleCount = 0;
        let eligibleCount = 0;
        let warningCount = 0;

        reportRows.forEach(row => {
            const status = row.dataset.status;
            const name = row.dataset.name || '';
            const roll = row.dataset.roll || '';

            const matchesStatus = selectedStatus === 'all' || status === selectedStatus;
            const matchesQuery = !q || name.includes(q) || roll.includes(q);

            if (matchesStatus && matchesQuery) {
                row.style.display = '';
                visibleCount++;
                if (status === 'eligible') eligibleCount++;
                else if (status === 'warning') warningCount++;
            } else {
                row.style.display = 'none';
            }
        });

        // Update summary metrics dynamically
        if (summaryStudents) summaryStudents.textContent = visibleCount;
        if (summaryEligible) summaryEligible.textContent = eligibleCount;
        if (summaryWarning) summaryWarning.textContent = warningCount;
    }

    courseFilter?.addEventListener('change', reloadWithScope);
    sectionFilter?.addEventListener('change', reloadWithScope);
    statusFilter?.addEventListener('change', applyFilters);
    searchInput?.addEventListener('input', applyFilters);

    // CSV Export Handler
    exportBtn?.addEventListener('click', async () => {
        const selectedCourse = courseFilter?.value || 'all';
        const selectedSection = sectionFilter?.value || 'all';
        exportBtn.disabled = true;
        exportBtn.innerHTML = '<span class="spinner-border spinner-border-sm me-2"></span> Generating CSV...';

        try {
            // Attempt backend export endpoint
            const url = `/api/reports/export-csv?course_id=${encodeURIComponent(selectedCourse)}&section=${encodeURIComponent(selectedSection)}`;
            const response = await fetch(url);

            if (response.ok && response.headers.get('content-type')?.includes('text/csv')) {
                const blob = await response.blob();
                downloadBlob(blob, `attendance_${selectedCourse}_${selectedSection}.csv`);
                showToast('Attendance report exported successfully', 'success');
            } else {
                let errMessage = 'Failed to export CSV report from server.';
                try {
                    const errData = await response.json();
                    if (errData && errData.error) errMessage = errData.error;
                } catch (_) {}
                showToast(errMessage, 'danger');
            }
        } catch (err) {
            console.error('Backend CSV export error:', err);
            showToast('Failed to export CSV: ' + err.message, 'danger');
        } finally {
            exportBtn.disabled = false;
            exportBtn.innerHTML = '<i class="bi bi-file-earmark-arrow-down-fill me-1"></i> Export CSV Report';
        }
    });

    // Client-side CSV generator fallback
    function exportTableToCsv() {
        const rows = [];
        rows.push(['Roll Number', 'Student Name', 'Course', 'Attended Sessions', 'Total Sessions', 'Attendance Percentage', 'Status']);

        reportRows.forEach(row => {
            if (row.style.display !== 'none') {
                const cells = row.querySelectorAll('td');
                if (cells.length >= 6) {
                    const rollNo = cells[0].textContent.trim();
                    const name = cells[1].textContent.trim();
                    const course = cells[2].textContent.trim();
                    const attendedText = cells[3].textContent.trim().replace(/\s+/g, ' ');
                    const [attended, total] = attendedText.split('/').map(s => s.trim());
                    const pctText = cells[4].querySelector('.font-monospace')?.textContent.trim() || '';
                    const statusText = cells[5].textContent.trim();

                    rows.push([
                        `"${rollNo}"`,
                        `"${name}"`,
                        `"${course}"`,
                        attended || '0',
                        total || '0',
                        `"${pctText}"`,
                        `"${statusText}"`
                    ]);
                }
            }
        });

        const csvContent = rows.map(e => e.join(',')).join('\n');
        const blob = new Blob([csvContent], { type: 'text/csv;charset=utf-8;' });
        downloadBlob(blob, `smart_attendance_report_${new Date().toISOString().slice(0,10)}.csv`);
    }

    function downloadBlob(blob, filename) {
        const link = document.createElement('a');
        const url = URL.createObjectURL(blob);
        link.setAttribute('href', url);
        link.setAttribute('download', filename);
        link.style.visibility = 'hidden';
        document.body.appendChild(link);
        link.click();
        document.body.removeChild(link);
    }
})();
