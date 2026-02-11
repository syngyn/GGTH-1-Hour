# GGTH-1-Hour
A machine learning system that predicts forex price movements using an ensemble of AI models and provides a Metatrader 5 Expert Advisor the data it needs to make trades.

This system is designed to use the 1 hour prediction on the EURUSD for fast trades and has shown 100% accuracy on the 1 hour prediction being filled within 120 hours (maximum). About 65% will close in the 1 hour window and another 25% within 24 hours.
It is designed to run without a stop loss because it will close the open trade in 120 hours. It will also use drawdown periods to average down the position to increase net profits knowing that it fills the prediction in 120 hours maximum
Run this on demo for awhile and you will that it preforms quite well and safely. Since it doesnt use a stop loss you will need to set the lot size as a static number and the averaging down lots. The biggest drawdown testing showed was 33%
So keep that in mind when deciding what percent to risk so you dont blow up your account.

Only enable the veto system if you feel its over trading. Otherwise the trend and rsi is enough to filter the trades properly.

IMPORTANT - for the system to work properly you need to be logged into the community portal on your Metatrader 5 platform: Click TOOLS - OPTIONS - COMMUNITY - then login.

