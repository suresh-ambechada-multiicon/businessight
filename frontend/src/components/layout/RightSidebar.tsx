import { memo, useCallback, useMemo } from "react";
import { FileText } from "lucide-react";

interface RightSidebarProps {
  interactions: any[];
}

export const RightSidebar = memo(function RightSidebar({ interactions }: RightSidebarProps) {
  const reports = useMemo(() => {
    return interactions
      .filter(
        (interaction) =>
          interaction.result?.report &&
          !interaction.result.report.includes("_Analysis cancelled by user._")
      )
      .map((interaction, index) => ({
        id: interaction.id || index,
        title: interaction.query,
        elementId: `interaction-${interaction.id || index}`,
      }));
  }, [interactions]);

  const scrollToInteraction = useCallback((elementId: string) => {
    const element = document.getElementById(elementId);
    if (element) {
      element.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  }, []);

  const handleScroll = useCallback((elementId: string) => {
    scrollToInteraction(elementId);
  }, [scrollToInteraction]);

  if (reports.length === 0) {
    return (
      <div className="right-sidebar">
        <div className="sidebar-header">
          <FileText size={20} />
          Report Outline
        </div>
        <div className="sidebar-content right-sidebar-empty">
          No reports generated yet.
        </div>
      </div>
    );
  }

  return (
    <div className="right-sidebar">
      <div className="sidebar-header">
        <FileText size={20} />
        Report Outline
      </div>
      <div className="sidebar-content right-sidebar-content">
        <div className="chat-list">
          {reports.map((report, idx) => (
            <div
              key={report.id}
              className="history-item report-outline-item"
              onClick={() => handleScroll(report.elementId)}
            >
              <div className="history-item-text report-outline-title">
                {idx + 1}. {report.title}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
});
