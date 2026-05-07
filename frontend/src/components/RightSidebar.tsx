import React from "react";
import { FileText } from "lucide-react";

interface RightSidebarProps {
  interactions: any[];
}

export const RightSidebar: React.FC<RightSidebarProps> = ({ interactions }) => {
  // Extract reports
  const reports = interactions
    .map((interaction, index) => {
      if (
        interaction.result &&
        interaction.result.report &&
        !interaction.result.report.includes("_Analysis cancelled by user._")
      ) {
        return {
          id: interaction.id || index,
          title: interaction.query,
          // Extract a short preview of the text, removing markdown characters like *, #
          summary:
            interaction.result.report.replace(/[*#]/g, "").substring(0, 100) +
            "...",
          elementId: `interaction-${interaction.id || index}`,
        };
      }
      return null;
    })
    .filter((report): report is NonNullable<typeof report> => report !== null);

  const scrollToInteraction = (elementId: string) => {
    const element = document.getElementById(elementId);
    if (element) {
      element.scrollIntoView({ behavior: "smooth", block: "start" });
    }
  };

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
          {reports.map((report: any, idx) => (
            <div
              key={report.id}
              className="history-item report-outline-item"
              onClick={() => scrollToInteraction(report.elementId)}
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
};
