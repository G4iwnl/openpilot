#pragma once

#include "selfdrive/ui/qt/widgets/controls.h"

class ModelPanel : public ListWidget {
  Q_OBJECT

public:
  explicit ModelPanel(QWidget *parent = nullptr);

private:
  Params params;
  LabelControl *currentModelLbl;

  void showEvent(QShowEvent *event) override;
  void updateLabels();
};
