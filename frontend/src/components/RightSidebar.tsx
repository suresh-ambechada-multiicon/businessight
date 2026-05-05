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
    .filter(Boolean);

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
        <div
          className="sidebar-content"
          style={{
            display: "flex",
            alignItems: "center",
            justifyContent: "center",
            flex: 1,
            opacity: 0.5,
            textAlign: "center",
            fontSize: "0.875rem",
            padding: "20px"
          }}
        >
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
      <div className="sidebar-content">
        <div className="chat-list">
          {reports.map((report: any, idx) => (
            <div
              key={report.id}
              className="history-item"
              style={{
                flexDirection: "column",
                alignItems: "flex-start",
                padding: "8px 12px",
                height: "auto",
                whiteSpace: "normal",
                cursor: "pointer",
                overflow: "visible",
                gap: "4px"
              }}
              onClick={() => scrollToInteraction(report.elementId)}
            >
              <div
                className="history-item-text"
                style={{
                  fontWeight: 600,
                  width: "100%",
                  whiteSpace: "normal",
                  overflow: "visible",
                  textOverflow: "clip",
                  lineHeight: "1.4",
                  fontSize: "0.85rem"
                }}
              >
                {idx + 1}. {report.title}
              </div>
            </div>
          ))}
        </div>
      </div>
    </div>
  );
};
