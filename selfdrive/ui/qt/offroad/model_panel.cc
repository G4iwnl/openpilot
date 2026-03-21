#include "selfdrive/ui/qt/offroad/model_panel.h"

ModelPanel::ModelPanel(QWidget *parent) : ListWidget(parent) {
  // Show current active model
  currentModelLbl = new LabelControl(tr("Current Model"), "");
  addItem(currentModelLbl);

  // Model generation selector
  auto modelSelector = new ButtonParamControl(
    "DrivingModelGeneration",
    tr("Driving Model"),
    tr("Select the driving model generation. Changes take effect after device restart. "
       "'Default' uses the standard model. 'Big' uses the larger model (if available)."),
    "",
    {tr("Default"), tr("Big")}
  );
  addItem(modelSelector);

  // Note about restart
  auto note = new LabelControl(
    tr("Note"),
    tr("A device restart is required after changing the model.")
  );
  addItem(note);
}

void ModelPanel::showEvent(QShowEvent *event) {
  ListWidget::showEvent(event);
  updateLabels();
}

void ModelPanel::updateLabels() {
  int gen = atoi(params.get("DrivingModelGeneration").c_str());
  QString modelName;
  switch (gen) {
    case 1:
      modelName = tr("Big Model");
      break;
    default:
      modelName = tr("Default Model");
      break;
  }
  currentModelLbl->setText(modelName);
}
